from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal

from opentelemetry import trace
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from eco_router.application.inference_models import (
    AttemptAccountingError,
    AttemptFinalization,
    AttemptIntent,
    ExecutionContext,
)
from eco_router.application.ports.inference import UsageSummary
from eco_router.domain.models import Currency, Money, PricingSnapshot
from eco_router.domain.services.accounting import AttemptStatus, ExecutionMode

_tracer = trace.get_tracer(__name__)


@asynccontextmanager
async def postgres_pool(
    database_url: str,
    *,
    min_size: int = 1,
    max_size: int = 4,
    timeout: float = 5.0,
) -> AsyncIterator[AsyncConnectionPool[AsyncConnection[tuple[object, ...]]]]:
    """Open a bounded pool and wait for its minimum connections before serving."""
    pool: AsyncConnectionPool[AsyncConnection[tuple[object, ...]]] = (
        AsyncConnectionPool(
            database_url,
            open=False,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            max_waiting=16,
        )
    )
    try:
        await pool.open(wait=True, timeout=timeout)
        yield pool
    finally:
        await pool.close()


def _pricing_values(pricing: PricingSnapshot) -> tuple[str, str, Decimal, Decimal]:
    return (
        pricing.model_id,
        pricing.snapshot_id,
        pricing.input_per_million,
        pricing.output_per_million,
    )


class PostgresAttemptLedger:
    """Persist the attempt lifecycle and summarize usage by tenant and mode."""

    def __init__(
        self, pool: AsyncConnectionPool[AsyncConnection[tuple[object, ...]]]
    ) -> None:
        self._pool = pool

    async def record_intent(self, intent: AttemptIntent) -> None:
        if (
            intent.binding.model_id != intent.candidate.model_id
            or intent.pricing.model_id != intent.candidate.model_id
            or intent.pricing.snapshot_id != intent.candidate.pricing_snapshot_id
        ):
            raise AttemptAccountingError("intent model, binding or pricing disagree")

        with _tracer.start_as_current_span(
            "ledger.record_intent",
            record_exception=False,
            set_status_on_exception=False,
        ):
            async with self._pool.connection() as connection:
                cursor = await connection.execute(
                    """
                    INSERT INTO inference_attempt (
                        tenant_id, execution_id, attempt_id, mode, provider_id,
                        model_id, pricing_snapshot_id, input_rate, output_rate
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, execution_id, attempt_id) DO NOTHING
                    """,
                    (
                        intent.context.tenant_id,
                        intent.context.execution_id,
                        intent.attempt_id,
                        intent.context.mode.value,
                        intent.binding.provider_id,
                        *_pricing_values(intent.pricing),
                    ),
                )
                if cursor.rowcount != 1:
                    raise AttemptAccountingError("duplicate attempt intent")

    async def finalize(self, finalization: AttemptFinalization) -> None:
        attempt = finalization.attempt
        if attempt.status is AttemptStatus.PENDING:
            raise AttemptAccountingError("finalization requires a terminal status")
        usage = attempt.usage
        cost = attempt.cost
        outcome = finalization.outcome
        values = (
            attempt.status.value,
            attempt.source.value,
            outcome.value if outcome is not None else None,
            finalization.dispatched,
            usage.input_tokens if usage is not None else None,
            usage.output_tokens if usage is not None else None,
            cost.amount if cost is not None else None,
        )
        identity = (
            finalization.context.tenant_id,
            finalization.context.execution_id,
            attempt.attempt_id,
            finalization.context.mode.value,
            *_pricing_values(attempt.pricing),
        )
        with _tracer.start_as_current_span(
            "ledger.finalize", record_exception=False, set_status_on_exception=False
        ):
            async with self._pool.connection() as connection:
                cursor = await connection.execute(
                    """
                    UPDATE inference_attempt
                    SET (status, source, outcome, dispatched, input_tokens,
                         output_tokens, cost) = (%s, %s, %s, %s, %s, %s, %s)
                    WHERE tenant_id = %s AND execution_id = %s AND attempt_id = %s
                      AND mode = %s AND model_id = %s AND pricing_snapshot_id = %s
                      AND input_rate = %s AND output_rate = %s AND status = 'pending'
                    """,
                    (*values, *identity),
                )
                if cursor.rowcount == 1:
                    return

                cursor = await connection.execute(
                    """
                    SELECT status, source, outcome, dispatched, input_tokens,
                           output_tokens, cost
                    FROM inference_attempt
                    WHERE tenant_id = %s AND execution_id = %s AND attempt_id = %s
                      AND mode = %s AND model_id = %s AND pricing_snapshot_id = %s
                      AND input_rate = %s AND output_rate = %s AND status <> 'pending'
                    """,
                    identity,
                )
                if await cursor.fetchone() != values:
                    raise AttemptAccountingError("missing or conflicting attempt")

    async def summarize(
        self,
        context: ExecutionContext,
        *,
        mode: ExecutionMode,
        start_utc: datetime,
        end_utc: datetime,
    ) -> UsageSummary:
        if (
            start_utc.utcoffset() != timedelta(0)
            or end_utc.utcoffset() != timedelta(0)
            or start_utc >= end_utc
        ):
            raise ValueError("usage range must be a nonempty UTC interval")

        with _tracer.start_as_current_span(
            "ledger.summarize", record_exception=False, set_status_on_exception=False
        ):
            async with self._pool.connection() as connection:
                cursor = await connection.execute(
                    """
                    SELECT count(*), coalesce(sum(input_tokens), 0),
                           coalesce(sum(output_tokens), 0), coalesce(sum(cost), 0),
                           count(*) FILTER (WHERE source = 'estimated'),
                           count(*) FILTER (WHERE source = 'unknown')
                    FROM inference_attempt
                    WHERE tenant_id = %s AND mode = %s
                      AND created_at >= %s AND created_at < %s
                      AND dispatched IS DISTINCT FROM FALSE
                    """,
                    (context.tenant_id, mode.value, start_utc, end_utc),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise AttemptAccountingError("usage aggregate is missing")
        attempts, input_tokens, output_tokens, cost, estimated, unresolved = row
        assert isinstance(attempts, int)
        assert isinstance(input_tokens, Decimal)
        assert isinstance(output_tokens, Decimal)
        assert isinstance(cost, Decimal)
        assert isinstance(estimated, int)
        assert isinstance(unresolved, int)
        return UsageSummary(
            attempts,
            int(input_tokens),
            int(output_tokens),
            Money(cost, Currency.USD),
            estimated,
            unresolved,
        )
