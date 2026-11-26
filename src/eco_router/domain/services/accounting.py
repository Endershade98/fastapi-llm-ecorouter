from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

from eco_router.domain.models import (
    DomainValidationError,
    Money,
    PricingSnapshot,
    TokenUsage,
    require_identifier,
    require_non_negative_int,
)


class ExecutionMode(StrEnum):
    LIVE = "live"
    SIMULATED = "simulated"


class UsageSource(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    ESTIMATED = "estimated"
    SIMULATED = "simulated"
    UNKNOWN = "unknown"


class AttemptStatus(StrEnum):
    PENDING = "pending"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


@dataclass(frozen=True, slots=True)
class AttemptUsage:
    attempt_id: str
    pricing: PricingSnapshot
    status: AttemptStatus
    source: UsageSource
    usage: TokenUsage | None

    def __post_init__(self) -> None:
        require_identifier(self.attempt_id, "attempt ID")
        if (self.source is UsageSource.UNKNOWN) != (self.usage is None):
            raise DomainValidationError("usage and usage source disagree")
        if self.status is AttemptStatus.PENDING and self.usage is not None:
            raise DomainValidationError("pending attempts must have unknown usage")

    @property
    def cost(self) -> Money | None:
        if self.usage is None:
            return None
        return price_usage(self.pricing, self.usage)


@dataclass(frozen=True, slots=True)
class Baseline:
    task_class: str
    pricing: PricingSnapshot
    estimated_input_tokens: int | None

    def __post_init__(self) -> None:
        require_identifier(self.task_class, "baseline task class")
        if self.estimated_input_tokens is not None:
            require_non_negative_int(
                self.estimated_input_tokens, "estimated baseline input tokens"
            )


@dataclass(frozen=True, slots=True)
class ExecutionAccounting:
    mode: ExecutionMode
    known_routed_cost: Money
    has_estimated_usage: bool
    unresolved_attempt_ids: tuple[str, ...]
    baseline_cost: Money | None
    counterfactual_savings: Money | None


def price_usage(pricing: PricingSnapshot, usage: TokenUsage) -> Money:
    """Price usage exactly and leave rounding to the reporting boundary."""
    amount = (
        Fraction(pricing.input_per_million) * usage.input_tokens
        + Fraction(pricing.output_per_million) * usage.output_tokens
    ) / 1_000_000
    return Money(_exact_decimal(amount), pricing.currency)


def summarize_execution(
    *,
    task_class: str,
    mode: ExecutionMode,
    baseline: Baseline,
    attempts: Iterable[AttemptUsage],
) -> ExecutionAccounting:
    """Summarize the attempts belonging to one routing execution."""
    require_identifier(task_class, "execution task class")
    if baseline.task_class != task_class:
        raise DomainValidationError("baseline belongs to another task class")

    seen_attempt_ids: set[str] = set()
    unresolved: list[str] = []
    total = Fraction(0)
    has_estimates = False
    success_seen = False
    observed_output_tokens: int | None = None

    for attempt in attempts:
        if attempt.attempt_id in seen_attempt_ids:
            raise DomainValidationError("duplicate attempt ID")
        seen_attempt_ids.add(attempt.attempt_id)
        _validate_source(mode, attempt.source)

        cost = attempt.cost
        if cost is None:
            unresolved.append(attempt.attempt_id)
        else:
            total += Fraction(cost.amount)
        has_estimates |= attempt.source is UsageSource.ESTIMATED

        if attempt.status is AttemptStatus.SUCCEEDED:
            if success_seen:
                raise DomainValidationError("multiple successful routing attempts")
            success_seen = True
            if (
                attempt.usage is not None
                and attempt.source is not UsageSource.ESTIMATED
            ):
                observed_output_tokens = attempt.usage.output_tokens

    baseline_cost = None
    savings = None
    if (
        baseline.estimated_input_tokens is not None
        and observed_output_tokens is not None
    ):
        baseline_cost = price_usage(
            baseline.pricing,
            TokenUsage(baseline.estimated_input_tokens, observed_output_tokens),
        )
        if not unresolved and not has_estimates:
            savings = Money(
                _exact_decimal(Fraction(baseline_cost.amount) - total),
                baseline.pricing.currency,
            )

    return ExecutionAccounting(
        mode=mode,
        known_routed_cost=Money(_exact_decimal(total), baseline.pricing.currency),
        has_estimated_usage=has_estimates,
        unresolved_attempt_ids=tuple(sorted(unresolved)),
        baseline_cost=baseline_cost,
        counterfactual_savings=savings,
    )


def _validate_source(mode: ExecutionMode, source: UsageSource) -> None:
    if source is UsageSource.UNKNOWN:
        return
    if (mode is ExecutionMode.SIMULATED) != (source is UsageSource.SIMULATED):
        raise DomainValidationError("usage source is incompatible with execution mode")


def _exact_decimal(value: Fraction) -> Decimal:
    """Convert a finite base-10 fraction without using the ambient context."""
    denominator = value.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise DomainValidationError("monetary amount has a nonterminating decimal")

    scale = max(twos, fives)
    coefficient = abs(value.numerator) * 2 ** (scale - twos) * 5 ** (scale - fives)
    digits = Decimal(coefficient).as_tuple().digits
    return Decimal((int(value < 0), digits, -scale))
