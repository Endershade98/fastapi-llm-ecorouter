from decimal import Decimal

import pytest

from eco_router.application.inference_models import (
    ExecutionLimits,
    InvalidExecutionPlan,
    ProviderContractError,
    ProviderOutcome,
    ProviderOutcomeKind,
)
from eco_router.domain.models import Currency, Money, TokenUsage
from eco_router.domain.services.accounting import UsageSource


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), float("-inf")])
def test_execution_limits_require_a_finite_deadline(deadline: float) -> None:
    with pytest.raises(InvalidExecutionPlan):
        ExecutionLimits(100, Money(Decimal("1"), Currency.USD), deadline, 1.0)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_execution_limits_require_a_positive_finite_attempt_timeout(
    timeout: float,
) -> None:
    with pytest.raises(InvalidExecutionPlan):
        ExecutionLimits(100, Money(Decimal("1"), Currency.USD), 10.0, timeout)


@pytest.mark.parametrize(
    ("kind", "source", "usage", "output", "provider_fault"),
    [
        pytest.param(
            ProviderOutcomeKind.SUCCEEDED,
            UsageSource.UNKNOWN,
            None,
            None,
            False,
            id="success-without-output",
        ),
        pytest.param(
            ProviderOutcomeKind.SUCCEEDED,
            UsageSource.UNKNOWN,
            None,
            "answer",
            True,
            id="success-marked-as-provider-fault",
        ),
        pytest.param(
            ProviderOutcomeKind.PERMANENT_FAILURE,
            UsageSource.UNKNOWN,
            None,
            "answer",
            False,
            id="failed-outcome-with-output",
        ),
        pytest.param(
            ProviderOutcomeKind.AMBIGUOUS_FAILURE,
            UsageSource.PROVIDER_REPORTED,
            None,
            None,
            True,
            id="reported-source-without-usage",
        ),
        pytest.param(
            ProviderOutcomeKind.AMBIGUOUS_FAILURE,
            UsageSource.UNKNOWN,
            TokenUsage(0, 0),
            None,
            True,
            id="unknown-source-with-usage",
        ),
        pytest.param(
            ProviderOutcomeKind.TRANSIENT_REJECTED,
            UsageSource.PROVIDER_REPORTED,
            TokenUsage(1, 0),
            None,
            False,
            id="confirmed-rejection-with-consumed-tokens",
        ),
    ],
)
def test_provider_outcome_rejects_inconsistent_data(
    kind: ProviderOutcomeKind,
    source: UsageSource,
    usage: TokenUsage | None,
    output: str | None,
    provider_fault: bool,
) -> None:
    with pytest.raises(ProviderContractError):
        ProviderOutcome(kind, source, usage, output, provider_fault)
