from dataclasses import replace

import pytest

from eco_router.domain.models import DomainValidationError, TokenUsage
from eco_router.domain.services.accounting import (
    AttemptStatus,
    AttemptUsage,
    Baseline,
    ExecutionMode,
    UsageSource,
    summarize_execution,
)

from .test_domain_data import TASK_CLASS, pricing, usd


@pytest.fixture
def baseline() -> Baseline:
    return Baseline(TASK_CLASS, pricing("reference"), 1_000)


@pytest.fixture
def successful_attempt() -> AttemptUsage:
    return AttemptUsage(
        "attempt-success",
        pricing("fallback"),
        AttemptStatus.SUCCEEDED,
        UsageSource.PROVIDER_REPORTED,
        TokenUsage(1_000, 500),
    )


def test_billable_failure_is_included_and_savings_can_be_negative(
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    failed = AttemptUsage(
        "attempt-failure",
        pricing("primary"),
        AttemptStatus.FAILED,
        UsageSource.PROVIDER_REPORTED,
        TokenUsage(500, 0),
    )
    result = summarize_execution(
        task_class=TASK_CLASS,
        mode=ExecutionMode.LIVE,
        baseline=baseline,
        attempts=iter((failed, successful_attempt)),
    )

    assert result.known_routed_cost == usd("0.005")
    assert result.baseline_cost == usd("0.004")
    assert result.counterfactual_savings == usd("-0.001")
    assert result.unresolved_attempt_ids == ()
    assert result.has_estimated_usage is False


def test_unknown_cost_preserves_known_subtotal_and_suppresses_savings(
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    unknown = AttemptUsage(
        "attempt-unknown",
        pricing("primary"),
        AttemptStatus.FAILED,
        UsageSource.UNKNOWN,
        None,
    )
    result = summarize_execution(
        task_class=TASK_CLASS,
        mode=ExecutionMode.LIVE,
        baseline=baseline,
        attempts=(unknown, successful_attempt),
    )

    assert unknown.cost is None
    assert result.known_routed_cost == usd("0.004")
    assert result.unresolved_attempt_ids == ("attempt-unknown",)
    assert result.counterfactual_savings is None


def test_estimated_usage_remains_distinguishable(
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    estimated = AttemptUsage(
        "attempt-estimated",
        pricing("primary"),
        AttemptStatus.FAILED,
        UsageSource.ESTIMATED,
        TokenUsage(500, 0),
    )
    result = summarize_execution(
        task_class=TASK_CLASS,
        mode=ExecutionMode.LIVE,
        baseline=baseline,
        attempts=(estimated, successful_attempt),
    )

    assert result.has_estimated_usage is True
    assert result.unresolved_attempt_ids == ()


def test_missing_baseline_input_preserves_routed_cost(
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    result = summarize_execution(
        task_class=TASK_CLASS,
        mode=ExecutionMode.LIVE,
        baseline=replace(baseline, estimated_input_tokens=None),
        attempts=(successful_attempt,),
    )

    assert result.known_routed_cost == usd("0.004")
    assert result.baseline_cost is None
    assert result.counterfactual_savings is None


def test_simulated_accounting_retains_execution_mode(
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    simulated = replace(successful_attempt, source=UsageSource.SIMULATED)
    result = summarize_execution(
        task_class=TASK_CLASS,
        mode=ExecutionMode.SIMULATED,
        baseline=baseline,
        attempts=(simulated,),
    )

    assert result.mode is ExecutionMode.SIMULATED
    assert result.known_routed_cost == usd("0.004")
    assert result.counterfactual_savings == usd("0")


@pytest.mark.parametrize(
    ("mode", "source"),
    [
        (ExecutionMode.LIVE, UsageSource.SIMULATED),
        (ExecutionMode.SIMULATED, UsageSource.PROVIDER_REPORTED),
        (ExecutionMode.SIMULATED, UsageSource.ESTIMATED),
    ],
)
def test_accounting_rejects_usage_from_an_incompatible_mode(
    mode: ExecutionMode,
    source: UsageSource,
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    with pytest.raises(DomainValidationError):
        summarize_execution(
            task_class=TASK_CLASS,
            mode=mode,
            baseline=baseline,
            attempts=(replace(successful_attempt, source=source),),
        )


def test_accounting_rejects_duplicate_attempt_ids(
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    failed_with_same_id = replace(successful_attempt, status=AttemptStatus.FAILED)
    with pytest.raises(DomainValidationError):
        summarize_execution(
            task_class=TASK_CLASS,
            mode=ExecutionMode.LIVE,
            baseline=baseline,
            attempts=(failed_with_same_id, successful_attempt),
        )


def test_accounting_rejects_multiple_successful_attempts(
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    second_success = replace(successful_attempt, attempt_id="another-success")
    with pytest.raises(DomainValidationError):
        summarize_execution(
            task_class=TASK_CLASS,
            mode=ExecutionMode.LIVE,
            baseline=baseline,
            attempts=(successful_attempt, second_success),
        )


def test_accounting_rejects_baseline_for_another_task_class(
    baseline: Baseline,
    successful_attempt: AttemptUsage,
) -> None:
    with pytest.raises(DomainValidationError):
        summarize_execution(
            task_class=TASK_CLASS,
            mode=ExecutionMode.LIVE,
            baseline=replace(baseline, task_class="other-task"),
            attempts=(successful_attempt,),
        )
