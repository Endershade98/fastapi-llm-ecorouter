import asyncio
from dataclasses import dataclass, field
from fractions import Fraction
from uuid import uuid4

from eco_router.application.circuit_breaker import CircuitBreaker
from eco_router.application.inference_models import (
    AttemptAccountingError,
    AttemptFinalization,
    AttemptIntent,
    ExecutionLimits,
    ExecutionStatus,
    InferenceRequest,
    InferenceResult,
    ModelBinding,
    ProviderCall,
    ProviderContractError,
    ProviderOutcome,
    ProviderOutcomeKind,
)
from eco_router.application.ports.inference import AttemptLedger, InferenceProvider
from eco_router.domain.models import PricingSnapshot, TokenUsage
from eco_router.domain.services.accounting import (
    AttemptStatus,
    AttemptUsage,
    ExecutionMode,
    UsageSource,
    price_usage,
    summarize_execution,
)
from eco_router.domain.services.routing import (
    RankedCandidate,
    RoutingResult,
    rank_candidates,
)

_MAX_PROVIDER_CALLS = 2


@dataclass(slots=True)
class _Execution:
    attempts: list[AttemptUsage] = field(default_factory=list)
    provider_calls: int = 0
    committed_tokens: int = 0
    committed_cost: Fraction = field(default_factory=Fraction)

    def fits(self, candidate: RankedCandidate, limits: ExecutionLimits) -> bool:
        maximum_cost = Fraction(candidate.estimated_maximum_cost.amount)
        return self.committed_tokens + _token_count(
            candidate.maximum_usage
        ) <= limits.max_tokens and self.committed_cost + maximum_cost <= Fraction(
            limits.max_cost.amount
        )

    def record(self, candidate: RankedCandidate, attempt: AttemptUsage) -> None:
        self.attempts.append(attempt)
        if attempt.source in (UsageSource.UNKNOWN, UsageSource.ESTIMATED):
            self.committed_tokens += _token_count(candidate.maximum_usage)
            self.committed_cost += Fraction(candidate.estimated_maximum_cost.amount)
            return

        usage = attempt.usage
        if usage is None:
            raise ProviderContractError("observed usage is missing")
        self.committed_tokens += _token_count(usage)
        self.committed_cost += Fraction(price_usage(attempt.pricing, usage).amount)


def _token_count(usage: TokenUsage) -> int:
    return usage.input_tokens + usage.output_tokens


def _exceeds_bound(usage: TokenUsage | None, bound: TokenUsage) -> bool:
    return usage is not None and (
        usage.input_tokens > bound.input_tokens
        or usage.output_tokens > bound.output_tokens
    )


class RouteInference:
    def __init__(
        self,
        provider: InferenceProvider,
        ledger: AttemptLedger,
        circuit: CircuitBreaker,
    ) -> None:
        self._provider = provider
        self._ledger = ledger
        self._circuit = circuit

    async def execute(self, request: InferenceRequest) -> InferenceResult:
        loop = asyncio.get_running_loop()
        routing = rank_candidates(
            request.constraints,
            request.catalog,
            request.token_bounds,
            request.policy,
        )
        execution = _Execution()

        if loop.time() >= request.limits.deadline:
            return self._result(
                request, routing, execution, ExecutionStatus.DEADLINE_EXCEEDED
            )
        if not routing.ranked:
            return self._result(
                request, routing, execution, ExecutionStatus.NO_ELIGIBLE_MODEL
            )

        bindings = {binding.model_id: binding for binding in request.bindings}
        prices = {
            model.model_id: model.pricing
            for model in request.catalog.models
            if model.pricing is not None
        }
        budget_blocked = False

        for candidate in routing.ranked:
            remaining_calls = _MAX_PROVIDER_CALLS - execution.provider_calls
            if remaining_calls == 0:
                break

            for _ in range(remaining_calls):
                if loop.time() >= request.limits.deadline:
                    return self._result(
                        request, routing, execution, ExecutionStatus.DEADLINE_EXCEEDED
                    )
                if not execution.fits(candidate, request.limits):
                    budget_blocked = True
                    break

                outcome = await self._dispatch(
                    request,
                    candidate,
                    bindings[candidate.model_id],
                    prices[candidate.model_id],
                    execution,
                )
                if outcome is None:
                    break

                if (
                    execution.committed_tokens > request.limits.max_tokens
                    or execution.committed_cost
                    > Fraction(request.limits.max_cost.amount)
                ):
                    return self._result(
                        request, routing, execution, ExecutionStatus.BUDGET_EXCEEDED
                    )

                if _exceeds_bound(outcome.usage, candidate.maximum_usage):
                    raise ProviderContractError(
                        "provider usage exceeded the candidate token bound"
                    )

                if loop.time() >= request.limits.deadline:
                    return self._result(
                        request, routing, execution, ExecutionStatus.DEADLINE_EXCEEDED
                    )

                if outcome.kind is ProviderOutcomeKind.SUCCEEDED:
                    return self._result(
                        request,
                        routing,
                        execution,
                        ExecutionStatus.SUCCEEDED,
                        output=outcome.output,
                        model_id=candidate.model_id,
                    )
                if outcome.kind is not ProviderOutcomeKind.TRANSIENT_REJECTED:
                    break

        if loop.time() >= request.limits.deadline:
            status = ExecutionStatus.DEADLINE_EXCEEDED
        elif execution.provider_calls == _MAX_PROVIDER_CALLS:
            status = ExecutionStatus.ATTEMPTS_EXHAUSTED
        elif budget_blocked:
            status = ExecutionStatus.BUDGET_EXCEEDED
        elif execution.provider_calls:
            status = ExecutionStatus.ATTEMPTS_EXHAUSTED
        else:
            status = ExecutionStatus.NO_ADMISSIBLE_ATTEMPT
        return self._result(request, routing, execution, status)

    async def _dispatch(
        self,
        request: InferenceRequest,
        candidate: RankedCandidate,
        binding: ModelBinding,
        pricing: PricingSnapshot,
        execution: _Execution,
    ) -> ProviderOutcome | None:
        loop = asyncio.get_running_loop()
        deadline = request.limits.deadline
        try:
            async with asyncio.timeout_at(deadline):
                available = await self._provider.is_available(request.context, binding)
        except TimeoutError:
            return None

        if available is not True or loop.time() >= deadline:
            return None

        permit = self._circuit.acquire(binding.provider_id, loop.time())
        if permit is None:
            return None

        provider_fault: bool | None = None
        intent = AttemptIntent(request.context, uuid4().hex, binding, candidate)
        try:
            try:
                async with asyncio.timeout_at(deadline):
                    await self._ledger.record_intent(intent)
            except Exception as exc:
                raise AttemptAccountingError(
                    "attempt intent was not confirmed"
                ) from exc

            if not self._circuit.is_current(permit) or loop.time() >= deadline:
                await self._finalize_skipped(request, intent, pricing)
                return None

            call = ProviderCall(
                request.context,
                intent.attempt_id,
                binding,
                request.prompt,
                candidate.maximum_usage,
            )
            attempt_deadline = min(
                deadline, loop.time() + request.limits.attempt_timeout_seconds
            )
            try:
                async with asyncio.timeout_at(attempt_deadline):
                    execution.provider_calls += 1
                    outcome = await self._provider.generate(call)
            except TimeoutError:
                outcome = ProviderOutcome(
                    ProviderOutcomeKind.AMBIGUOUS_FAILURE,
                    provider_fault=True,
                )

            provider_fault = outcome.provider_fault
            attempt = self._accounted_attempt(
                request.context.mode, intent, pricing, outcome
            )
            await self._finalize(
                request,
                AttemptFinalization(request.context, attempt, outcome.kind, True),
            )
            execution.record(candidate, attempt)
            return outcome
        finally:
            self._circuit.finish(permit, loop.time(), provider_fault=provider_fault)

    async def _finalize_skipped(
        self,
        request: InferenceRequest,
        intent: AttemptIntent,
        pricing: PricingSnapshot,
    ) -> None:
        source = (
            UsageSource.SIMULATED
            if request.context.mode is ExecutionMode.SIMULATED
            else UsageSource.ESTIMATED
        )
        attempt = AttemptUsage(
            intent.attempt_id, pricing, AttemptStatus.FAILED, source, TokenUsage(0, 0)
        )
        await self._finalize(
            request, AttemptFinalization(request.context, attempt, None, False)
        )

    async def _finalize(
        self,
        request: InferenceRequest,
        finalization: AttemptFinalization,
    ) -> None:
        try:
            async with asyncio.timeout_at(request.limits.deadline):
                await self._ledger.finalize(finalization)
        except Exception as exc:
            raise AttemptAccountingError(
                "attempt finalization was not confirmed"
            ) from exc

    @staticmethod
    def _accounted_attempt(
        mode: ExecutionMode,
        intent: AttemptIntent,
        pricing: PricingSnapshot,
        outcome: ProviderOutcome,
    ) -> AttemptUsage:
        source = outcome.source
        usage = outcome.usage
        if source is not UsageSource.UNKNOWN and (
            (mode is ExecutionMode.SIMULATED) != (source is UsageSource.SIMULATED)
        ):
            raise ProviderContractError("provider usage source does not match mode")

        if outcome.kind is ProviderOutcomeKind.TRANSIENT_REJECTED and usage is None:
            # Rejection before acceptance proves that no usage was incurred.
            # E01 represents live zero-usage estimates with ESTIMATED.
            source = (
                UsageSource.SIMULATED
                if mode is ExecutionMode.SIMULATED
                else UsageSource.ESTIMATED
            )
            usage = TokenUsage(0, 0)

        status = (
            AttemptStatus.SUCCEEDED
            if outcome.kind is ProviderOutcomeKind.SUCCEEDED
            else AttemptStatus.FAILED
        )
        return AttemptUsage(intent.attempt_id, pricing, status, source, usage)

    @staticmethod
    def _result(
        request: InferenceRequest,
        routing: RoutingResult,
        execution: _Execution,
        status: ExecutionStatus,
        *,
        output: str | None = None,
        model_id: str | None = None,
    ) -> InferenceResult:
        attempts = tuple(execution.attempts)
        accounting = summarize_execution(
            task_class=request.constraints.task_class,
            mode=request.context.mode,
            baseline=request.baseline,
            attempts=attempts,
        )
        return InferenceResult(status, routing, attempts, accounting, output, model_id)
