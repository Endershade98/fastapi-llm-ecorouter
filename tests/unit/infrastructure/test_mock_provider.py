import asyncio
from dataclasses import replace

import pytest

from eco_router.application.inference_models import (
    ExecutionContext,
    ModelBinding,
    ProviderCall,
    ProviderOutcome,
    ProviderOutcomeKind,
)
from eco_router.domain.models import TokenUsage
from eco_router.domain.services.accounting import ExecutionMode, UsageSource
from eco_router.infrastructure.adapters.mock_provider import MockInferenceProvider


def build_call() -> ProviderCall:
    return ProviderCall(
        ExecutionContext("tenant-a", "execution-a", ExecutionMode.SIMULATED),
        "attempt-a",
        ModelBinding("primary", "mock"),
        "Summarize this",
        TokenUsage(2, 2),
    )


@pytest.mark.parametrize(("cap", "output"), [(0, ""), (2, "Simulated inference")])
def test_success_is_deterministic_and_respects_output_cap(
    cap: int, output: str
) -> None:
    provider = MockInferenceProvider()
    call = replace(build_call(), maximum_usage=TokenUsage(2, cap))

    expected = ProviderOutcome(
        ProviderOutcomeKind.SUCCEEDED, UsageSource.SIMULATED, TokenUsage(2, cap), output
    )
    assert asyncio.run(provider.generate(call)) == expected
    assert asyncio.run(provider.generate(call)) == expected


def test_configured_rejection_preserves_availability_and_reports_zero_usage() -> None:
    provider = MockInferenceProvider(rejected_model_ids=frozenset({"primary"}))
    call = build_call()
    fallback = replace(call, binding=ModelBinding("fallback", "mock"))

    assert asyncio.run(provider.is_available(call.context, call.binding))
    assert asyncio.run(provider.generate(call)) == ProviderOutcome(
        ProviderOutcomeKind.TRANSIENT_REJECTED, UsageSource.SIMULATED, TokenUsage(0, 0)
    )
    assert (
        asyncio.run(provider.generate(fallback)).kind is ProviderOutcomeKind.SUCCEEDED
    )


def test_input_over_bound_is_rejected_before_consumption() -> None:
    call = replace(build_call(), maximum_usage=TokenUsage(1, 2))

    assert asyncio.run(MockInferenceProvider().generate(call)) == ProviderOutcome(
        ProviderOutcomeKind.PERMANENT_FAILURE, UsageSource.SIMULATED, TokenUsage(0, 0)
    )


@pytest.mark.parametrize(
    ("mode", "provider_id"),
    [(ExecutionMode.LIVE, "mock"), (ExecutionMode.SIMULATED, "other")],
)
def test_rejects_live_mode_and_foreign_binding(
    mode: ExecutionMode, provider_id: str
) -> None:
    provider = MockInferenceProvider()
    call = build_call()
    call = replace(
        call,
        context=replace(call.context, mode=mode),
        binding=replace(call.binding, provider_id=provider_id),
    )

    assert not asyncio.run(provider.is_available(call.context, call.binding))
    assert (
        asyncio.run(provider.generate(call)).kind
        is ProviderOutcomeKind.PERMANENT_FAILURE
    )
