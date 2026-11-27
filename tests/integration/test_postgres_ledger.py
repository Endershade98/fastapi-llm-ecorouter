import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import make_conninfo

from eco_router.application.inference_models import (
    AttemptAccountingError,
    AttemptFinalization,
    AttemptIntent,
    ExecutionContext,
    ModelBinding,
    ProviderOutcomeKind,
)
from eco_router.domain.models import Currency, Money, PricingSnapshot, TokenUsage
from eco_router.domain.services.accounting import (
    AttemptStatus,
    AttemptUsage,
    ExecutionMode,
    UsageSource,
)
from eco_router.domain.services.routing import RankedCandidate
from eco_router.infrastructure.persistence.postgres import (
    PostgresAttemptLedger,
    postgres_pool,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def database_url(monkeypatch):
    dsn = os.getenv("ECOROUTER_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip(
            "ECOROUTER_TEST_DATABASE_URL is required for PostgreSQL integration"
        )

    schema = f"test_{uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        create_schema = sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        admin.execute(create_schema)
        try:
            isolated = make_conninfo(dsn, options=f"-c search_path={schema}")
            monkeypatch.setenv("ECOROUTER_DATABASE_URL", isolated)
            command.upgrade(
                Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head"
            )
            yield isolated
        finally:
            admin.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def test_ledger_survives_reconnection_and_preserves_tenant_and_mode(database_url):
    async def exercise():
        start = datetime.now(UTC) - timedelta(minutes=1)
        end = start + timedelta(minutes=2)
        context = ExecutionContext("tenant-a", "execution-a", ExecutionMode.SIMULATED)
        other_tenant = replace(context, tenant_id="tenant-b")
        live = replace(context, execution_id="live", mode=ExecutionMode.LIVE)
        pricing = PricingSnapshot(
            "price", "primary", Currency.USD, Decimal(2), Decimal(4)
        )
        candidate = RankedCandidate(
            "primary",
            "price",
            95,
            TokenUsage(2, 2),
            Money(Decimal("0.001"), Currency.USD),
            20,
            95,
        )
        intent = AttemptIntent(
            context, "attempt", ModelBinding("primary", "mock"), candidate, pricing
        )
        attempt = AttemptUsage(
            intent.attempt_id,
            pricing,
            AttemptStatus.SUCCEEDED,
            UsageSource.SIMULATED,
            TokenUsage(2, 1),
        )
        finalization = AttemptFinalization(
            context, attempt, ProviderOutcomeKind.SUCCEEDED, True
        )

        async with postgres_pool(database_url, max_size=1) as pool:
            ledger = PostgresAttemptLedger(pool)
            await ledger.record_intent(intent)
            with pytest.raises(AttemptAccountingError, match="duplicate"):
                await ledger.record_intent(intent)
            await ledger.record_intent(replace(intent, context=other_tenant))
            await ledger.record_intent(replace(intent, context=live))
            await ledger.finalize(finalization)
            await ledger.finalize(finalization)
            changed = replace(attempt, usage=TokenUsage(2, 2))
            with pytest.raises(AttemptAccountingError, match="conflicting"):
                await ledger.finalize(replace(finalization, attempt=changed))

        async with postgres_pool(database_url, max_size=1) as pool:
            ledger = PostgresAttemptLedger(pool)
            summary = await ledger.summarize(
                context, mode=context.mode, start_utc=start, end_utc=end
            )
            assert summary.attempts == 1
            assert summary.known_input_tokens == 2
            assert summary.known_output_tokens == 1
            assert summary.known_cost == Money(Decimal("0.000008"), Currency.USD)
            assert summary.unresolved_attempts == 0
            other = await ledger.summarize(
                other_tenant, mode=context.mode, start_utc=start, end_utc=end
            )
            assert other.attempts == other.unresolved_attempts == 1
            assert other.known_cost == Money(Decimal(0), Currency.USD)
            live_summary = await ledger.summarize(
                context, mode=live.mode, start_utc=start, end_utc=end
            )
            assert live_summary.attempts == live_summary.unresolved_attempts == 1
            outside = await ledger.summarize(
                context,
                mode=context.mode,
                start_utc=end,
                end_utc=end + timedelta(minutes=1),
            )
            assert outside.attempts == 0

    asyncio.run(exercise())
