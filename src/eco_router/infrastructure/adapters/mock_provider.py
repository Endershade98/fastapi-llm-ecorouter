from eco_router.application.inference_models import (
    ExecutionContext,
    ModelBinding,
    ProviderCall,
    ProviderOutcome,
    ProviderOutcomeKind,
)
from eco_router.domain.models import TokenUsage, require_identifier
from eco_router.domain.services.accounting import ExecutionMode, UsageSource

_RESPONSE = ("Simulated", "inference", "response.")


class MockInferenceProvider:
    """Deterministic provider for simulated requests with synthetic word counts."""

    def __init__(
        self,
        provider_id: str = "mock",
        *,
        rejected_model_ids: frozenset[str] = frozenset(),
    ) -> None:
        require_identifier(provider_id, "mock provider ID")
        for model_id in rejected_model_ids:
            require_identifier(model_id, "rejected model ID")
        self._provider_id = provider_id
        self._rejected_model_ids = rejected_model_ids

    async def is_available(
        self, context: ExecutionContext, binding: ModelBinding
    ) -> bool:
        return (
            context.mode is ExecutionMode.SIMULATED
            and binding.provider_id == self._provider_id
        )

    async def generate(self, call: ProviderCall) -> ProviderOutcome:
        if not await self.is_available(call.context, call.binding):
            return ProviderOutcome(ProviderOutcomeKind.PERMANENT_FAILURE)

        input_tokens = len(call.prompt.split())
        if input_tokens > call.maximum_usage.input_tokens:
            return ProviderOutcome(
                ProviderOutcomeKind.PERMANENT_FAILURE,
                UsageSource.SIMULATED,
                TokenUsage(0, 0),
            )
        if call.binding.model_id in self._rejected_model_ids:
            return ProviderOutcome(
                ProviderOutcomeKind.TRANSIENT_REJECTED,
                UsageSource.SIMULATED,
                TokenUsage(0, 0),
            )

        output = _RESPONSE[: call.maximum_usage.output_tokens]
        return ProviderOutcome(
            ProviderOutcomeKind.SUCCEEDED,
            UsageSource.SIMULATED,
            TokenUsage(input_tokens, len(output)),
            " ".join(output),
        )
