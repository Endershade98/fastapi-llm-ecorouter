from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from eco_router.application.inference_models import (
    AttemptFinalization,
    AttemptIntent,
    ExecutionContext,
    ModelBinding,
    ProviderCall,
    ProviderOutcome,
)
from eco_router.domain.models import Money
from eco_router.domain.services.accounting import ExecutionMode


class InferenceProvider(Protocol):
    async def is_available(
        self, context: ExecutionContext, binding: ModelBinding
    ) -> bool:
        """Check current dispatch eligibility for this binding."""

    async def generate(self, call: ProviderCall) -> ProviderOutcome:
        """Execute one provider attempt.

        The adapter must enforce the output cap and disable SDK retries. It
        must classify operational failures and report usage when available.
        A transient rejection requires evidence that the request was not accepted.
        """


class AttemptLedger(Protocol):
    async def record_intent(self, intent: AttemptIntent) -> None:
        """Persist a pending intent before returning.

        The key is tenant, execution and attempt. A duplicate intent must
        raise before dispatch, even if its payload matches an existing row.
        """

    async def finalize(self, finalization: AttemptFinalization) -> None:
        """Transition a pending intent to a terminal state.

        A repeated identical finalization may succeed. Conflicting updates
        must raise. Both operations must preserve tenant scope.
        """


@dataclass(frozen=True, slots=True)
class UsageSummary:
    attempts: int
    known_input_tokens: int
    known_output_tokens: int
    known_cost: Money
    estimated_attempts: int
    unresolved_attempts: int


class UsageAnalytics(Protocol):
    async def summarize(
        self,
        context: ExecutionContext,
        *,
        mode: ExecutionMode,
        start_utc: datetime,
        end_utc: datetime,
    ) -> UsageSummary:
        """Read usage for the context tenant and mode in a half-open UTC interval.

        Callers authorize access and validate the time range before invoking
        this port. Implementations scope all reads by tenant and mode.
        """
