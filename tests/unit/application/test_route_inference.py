import asyncio
from collections import deque
from dataclasses import replace
from decimal import Decimal

import pytest

from eco_router.application.circuit_breaker import CircuitBreaker
from eco_router.application.inference_models import (
    AttemptAccountingError,
    AttemptFinalization,
    AttemptIntent,
    ExecutionContext,
    ExecutionLimits,
    ExecutionStatus,
    InferenceRequest,
    InferenceResult,
    InvalidExecutionPlan,
    ModelBinding,
    ProviderCall,
    ProviderContractError,
    ProviderOutcome,
    ProviderOutcomeKind,
)
from eco_router.application.use_cases.route_inference import RouteInference
from eco_router.domain.models import (
    CatalogSnapshot,
    Currency,
    ModelSnapshot,
    Money,
    PricingSnapshot,
    QualityRating,
    TokenUsage,
)
from eco_router.domain.services.accounting import (
    AttemptStatus,
    Baseline,
    ExecutionMode,
    UsageSource,
)
from eco_router.domain.services.routing import (
    CandidateTokenBounds,
    RoutingConstraints,
    RoutingPolicy,
)

TASK_CLASS = "summarization"


def usd(amount: str) -> Money:
    return Money(Decimal(amount), Currency.USD)


def pricing(model_id: str) -> PricingSnapshot:
    return PricingSnapshot(
        f"price-{model_id}", model_id, Currency.USD, Decimal("2"), Decimal("4")
    )


def build_request() -> InferenceRequest:
    models = tuple(
        ModelSnapshot(
            model_id=model_id,
            capabilities=frozenset({"text"}),
            quality_ratings=(QualityRating(TASK_CLASS, quality, "test-data"),),
            available=True,
            pricing=pricing(model_id),
            estimated_latency_ms=20,
            context_window_tokens=1_500,
            max_output_tokens=500,
        )
        for model_id, quality in (("primary", 95), ("fallback", 85))
    )
    return InferenceRequest(
        context=ExecutionContext("tenant-a", "execution-a", ExecutionMode.SIMULATED),
        prompt="Summarize the test document.",
        constraints=RoutingConstraints(
            TASK_CLASS, 80, frozenset({"text"}), usd("0.004"), 100
        ),
        catalog=CatalogSnapshot("catalog-v1", models),
        token_bounds=tuple(
            CandidateTokenBounds(model.model_id, TokenUsage(1_000, 500))
            for model in models
        ),
        bindings=(
            ModelBinding("primary", "provider-a"),
            ModelBinding("fallback", "provider-b"),
        ),
        policy=RoutingPolicy("policy-v1", 1, 0, 0, Decimal("1"), 100),
        baseline=Baseline(TASK_CLASS, pricing("reference"), 1_000),
        limits=ExecutionLimits(4_500, usd("0.012"), 0.0, 10.0),
    )


class ScriptedProvider:
    def __init__(
        self,
        outcomes: tuple[ProviderOutcome, ...],
        *,
        unavailable: frozenset[str] = frozenset(),
    ) -> None:
        self.outcomes = deque(outcomes)
        self.unavailable = unavailable
        self.calls: list[ProviderCall] = []
        self.availability_checks: list[tuple[ExecutionContext, ModelBinding]] = []
        self.events: list[tuple[str, str]] = []

    async def is_available(
        self, context: ExecutionContext, binding: ModelBinding
    ) -> bool:
        self.availability_checks.append((context, binding))
        return binding.model_id not in self.unavailable

    async def generate(self, call: ProviderCall) -> ProviderOutcome:
        self.calls.append(call)
        self.events.append(("generate", call.attempt_id))
        return self.outcomes.popleft()


class RecordingLedger:
    def __init__(
        self,
        events: list[tuple[str, str]],
        *,
        fail_at: str | None = None,
    ) -> None:
        self.events = events
        self.fail_at = fail_at
        self.intents: list[AttemptIntent] = []
        self.finalizations: list[AttemptFinalization] = []

    async def record_intent(self, intent: AttemptIntent) -> None:
        if self.fail_at == "intent":
            raise RuntimeError("intent write failed")
        self.intents.append(intent)
        self.events.append(("intent", intent.attempt_id))

    async def finalize(self, finalization: AttemptFinalization) -> None:
        if self.fail_at == "finalize":
            raise RuntimeError("finalization write failed")
        self.finalizations.append(finalization)
        self.events.append(("finalize", finalization.attempt.attempt_id))


def success(
    usage: TokenUsage | None = None,
    source: UsageSource = UsageSource.SIMULATED,
) -> ProviderOutcome:
    if usage is None:
        usage = TokenUsage(1_000, 500)

    return ProviderOutcome(ProviderOutcomeKind.SUCCEEDED, source, usage, "summary")


def run_inference(
    request: InferenceRequest,
    provider: ScriptedProvider,
    ledger: RecordingLedger,
    *,
    expired: bool = False,
    breaker: CircuitBreaker | None = None,
) -> InferenceResult:
    async def execute() -> InferenceResult:
        now = asyncio.get_running_loop().time()
        deadline = now - 1.0 if expired else now + 60.0
        active_request = replace(
            request, limits=replace(request.limits, deadline=deadline)
        )
        use_case = RouteInference(provider, ledger, breaker or CircuitBreaker())
        return await use_case.execute(active_request)

    return asyncio.run(execute())


def test_success_persists_intent_before_dispatch_and_finalizes_same_attempt() -> None:
    request = build_request()
    provider = ScriptedProvider((success(),))
    ledger = RecordingLedger(provider.events)

    result = run_inference(request, provider, ledger)

    (call,) = provider.calls
    (intent,) = ledger.intents
    (finalization,) = ledger.finalizations
    assert provider.events == [
        ("intent", call.attempt_id),
        ("generate", call.attempt_id),
        ("finalize", call.attempt_id),
    ]
    assert intent.context == call.context == finalization.context == request.context
    assert intent.binding == call.binding == request.bindings[0]
    assert call.prompt == request.prompt
    assert call.maximum_usage == TokenUsage(1_000, 500)
    assert finalization.dispatched
    assert finalization.attempt.status is AttemptStatus.SUCCEEDED
    assert result.attempts == (finalization.attempt,)
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.model_id == "primary"
    assert result.output == "summary"
    assert result.accounting.known_routed_cost == usd("0.004")


@pytest.mark.parametrize(
    ("expired", "quality_floor", "status"),
    [
        (True, 80, ExecutionStatus.DEADLINE_EXCEEDED),
        (False, 100, ExecutionStatus.NO_ELIGIBLE_MODEL),
    ],
)
def test_inadmissible_execution_does_not_touch_provider_or_ledger(
    expired: bool,
    quality_floor: int,
    status: ExecutionStatus,
) -> None:
    request = build_request()
    request = replace(
        request, constraints=replace(request.constraints, minimum_quality=quality_floor)
    )
    provider = ScriptedProvider(())
    ledger = RecordingLedger(provider.events)

    result = run_inference(request, provider, ledger, expired=expired)

    assert result.status is status
    assert result.attempts == ()
    assert provider.availability_checks == []
    assert provider.events == []


def test_primary_unavailable_at_dispatch_skips_to_next_eligible_model() -> None:
    request = build_request()
    provider = ScriptedProvider((success(),), unavailable=frozenset({"primary"}))
    ledger = RecordingLedger(provider.events)

    result = run_inference(request, provider, ledger)

    assert [binding.model_id for _, binding in provider.availability_checks] == [
        "primary",
        "fallback",
    ]
    assert [call.binding.model_id for call in provider.calls] == ["fallback"]
    assert len(ledger.intents) == len(ledger.finalizations) == 1
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.model_id == "fallback"


def test_ambiguous_failure_uses_distinct_fallback_and_preserves_unknown_cost() -> None:
    request = build_request()
    ambiguous = ProviderOutcome(ProviderOutcomeKind.AMBIGUOUS_FAILURE)
    provider = ScriptedProvider((ambiguous, success()))
    ledger = RecordingLedger(provider.events)

    result = run_inference(request, provider, ledger)

    assert [call.binding.model_id for call in provider.calls] == ["primary", "fallback"]
    first, second = result.attempts
    assert first.attempt_id != second.attempt_id
    assert first.status is AttemptStatus.FAILED
    assert first.source is UsageSource.UNKNOWN
    assert second.status is AttemptStatus.SUCCEEDED
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.model_id == "fallback"
    assert result.accounting.known_routed_cost == usd("0.004")
    assert result.accounting.unresolved_attempt_ids == (first.attempt_id,)
    assert result.accounting.counterfactual_savings is None


@pytest.mark.parametrize(
    ("max_tokens", "max_cost"),
    [(2_999, "0.008"), (3_000, "0.007999")],
    ids=["token-budget", "cost-budget"],
)
def test_ambiguous_attempt_retains_reservation_and_blocks_fallback(
    max_tokens: int, max_cost: str
) -> None:
    request = build_request()
    request = replace(
        request,
        limits=replace(request.limits, max_tokens=max_tokens, max_cost=usd(max_cost)),
    )
    provider = ScriptedProvider(
        (ProviderOutcome(ProviderOutcomeKind.AMBIGUOUS_FAILURE),)
    )
    ledger = RecordingLedger(provider.events)

    result = run_inference(request, provider, ledger)

    assert result.status is ExecutionStatus.BUDGET_EXCEEDED
    assert [call.binding.model_id for call in provider.calls] == ["primary"]
    assert len(ledger.intents) == len(ledger.finalizations) == 1


def test_known_usage_releases_unused_reservation_for_fallback() -> None:
    request = build_request()
    request = replace(
        request,
        limits=replace(request.limits, max_tokens=2_000, max_cost=usd("0.005")),
    )
    billable_failure = ProviderOutcome(
        ProviderOutcomeKind.AMBIGUOUS_FAILURE,
        UsageSource.SIMULATED,
        TokenUsage(500, 0),
    )
    provider = ScriptedProvider((billable_failure, success()))
    ledger = RecordingLedger(provider.events)

    result = run_inference(request, provider, ledger)

    assert result.status is ExecutionStatus.SUCCEEDED
    assert [call.binding.model_id for call in provider.calls] == ["primary", "fallback"]
    assert result.accounting.known_routed_cost == usd("0.005")
    assert result.accounting.counterfactual_savings == usd("-0.001")


def test_mvp_allows_at_most_two_provider_calls_across_retry_and_fallback() -> None:
    # Supply a third outcome so a third dispatch produces an explicit assertion
    # failure, rather than failing because the scripted outcomes ran out.
    rejection = ProviderOutcome(ProviderOutcomeKind.TRANSIENT_REJECTED)
    provider = ScriptedProvider((rejection, rejection, success()))
    ledger = RecordingLedger(provider.events)

    result = run_inference(build_request(), provider, ledger)

    dispatched_models = [call.binding.model_id for call in provider.calls]
    assert len(dispatched_models) == 2, dispatched_models
    assert result.status is ExecutionStatus.ATTEMPTS_EXHAUSTED
    assert len(ledger.intents) == len(ledger.finalizations) == 2


@pytest.mark.parametrize(
    ("failure", "expected_calls"),
    [("intent", 0), ("finalize", 1)],
)
def test_ledger_failure_prevents_further_provider_dispatch(
    failure: str, expected_calls: int
) -> None:
    provider = ScriptedProvider(
        (ProviderOutcome(ProviderOutcomeKind.AMBIGUOUS_FAILURE), success())
    )
    ledger = RecordingLedger(provider.events, fail_at=failure)

    with pytest.raises(AttemptAccountingError) as error:
        run_inference(build_request(), provider, ledger)

    assert isinstance(error.value.__cause__, RuntimeError)
    assert len(provider.calls) == expected_calls
    assert len(ledger.intents) == expected_calls
    assert ledger.finalizations == []


def test_provider_usage_from_wrong_execution_mode_is_rejected() -> None:
    provider = ScriptedProvider((success(source=UsageSource.PROVIDER_REPORTED),))
    ledger = RecordingLedger(provider.events)

    with pytest.raises(ProviderContractError):
        run_inference(build_request(), provider, ledger)

    assert len(provider.calls) == 1


def test_provider_usage_above_candidate_bound_is_rejected() -> None:
    provider = ScriptedProvider((success(usage=TokenUsage(999, 501)),))
    ledger = RecordingLedger(provider.events)

    with pytest.raises(ProviderContractError):
        run_inference(build_request(), provider, ledger)

    assert len(provider.calls) == 1


def test_request_rejects_baseline_for_another_task_class() -> None:
    request = build_request()

    with pytest.raises(InvalidExecutionPlan):
        replace(
            request, baseline=replace(request.baseline, task_class="classification")
        )


@pytest.mark.parametrize("invalid_bindings", ["missing", "duplicate", "foreign"])
def test_request_requires_exactly_one_binding_per_catalog_model(
    invalid_bindings: str,
) -> None:
    request = build_request()
    primary, fallback = request.bindings
    bindings = {
        "missing": (primary,),
        "duplicate": (primary, primary, fallback),
        "foreign": (primary, ModelBinding("foreign", "provider-c")),
    }[invalid_bindings]

    with pytest.raises(InvalidExecutionPlan):
        replace(request, bindings=bindings)
