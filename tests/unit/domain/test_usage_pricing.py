from decimal import localcontext

import pytest

from eco_router.domain.models import DomainValidationError, TokenUsage
from eco_router.domain.services.accounting import (
    AttemptStatus,
    AttemptUsage,
    UsageSource,
    price_usage,
)

from .test_domain_data import pricing, usd


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (TokenUsage(0, 0), "0"),
        (TokenUsage(1, 0), "0.000000125"),
        (TokenUsage(0, 1), "0.00000275"),
        (TokenUsage(3, 2), "0.000005875"),
    ],
)
def test_price_usage_is_exact_under_low_decimal_precision(
    usage: TokenUsage,
    expected: str,
) -> None:
    snapshot = pricing("alpha", input_rate="0.125", output_rate="2.75")
    with localcontext() as context:
        context.prec = 2
        actual = price_usage(snapshot, usage)

    assert actual == usd(expected)


@pytest.mark.parametrize(
    ("status", "source", "usage"),
    [
        (AttemptStatus.FAILED, UsageSource.UNKNOWN, TokenUsage(0, 0)),
        (AttemptStatus.SUCCEEDED, UsageSource.PROVIDER_REPORTED, None),
        (AttemptStatus.PENDING, UsageSource.PROVIDER_REPORTED, TokenUsage(0, 0)),
    ],
    ids=["unknown-with-tokens", "reported-without-tokens", "pending-with-tokens"],
)
def test_attempt_rejects_inconsistent_status_and_usage(
    status: AttemptStatus,
    source: UsageSource,
    usage: TokenUsage | None,
) -> None:
    with pytest.raises(DomainValidationError):
        AttemptUsage("attempt-1", pricing("alpha"), status, source, usage)
