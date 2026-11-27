from alembic import op

revision = "0001_attempt_ledger"
down_revision = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inference_attempt (
            tenant_id text NOT NULL,
            execution_id text NOT NULL,
            attempt_id text NOT NULL,
            mode text NOT NULL CHECK (mode IN ('live', 'simulated')),
            provider_id text NOT NULL,
            model_id text NOT NULL,
            pricing_snapshot_id text NOT NULL,
            input_rate numeric NOT NULL CHECK (input_rate >= 0),
            output_rate numeric NOT NULL CHECK (output_rate >= 0),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'failed', 'succeeded')),
            source text NOT NULL DEFAULT 'unknown'
                CHECK (source IN (
                    'unknown', 'estimated', 'simulated', 'provider_reported'
                )),
            outcome text CHECK (outcome IN (
                'succeeded', 'transient_rejected', 'permanent_failure',
                'ambiguous_failure'
            )),
            dispatched boolean,
            input_tokens numeric CHECK (input_tokens >= 0),
            output_tokens numeric CHECK (output_tokens >= 0),
            cost numeric CHECK (cost >= 0),
            PRIMARY KEY (tenant_id, execution_id, attempt_id),
            CHECK (
                (source = 'unknown' AND input_tokens IS NULL
                 AND output_tokens IS NULL AND cost IS NULL)
                OR (source <> 'unknown' AND input_tokens IS NOT NULL
                    AND output_tokens IS NOT NULL AND cost IS NOT NULL)
            ),
            CHECK (
                (status = 'pending' AND dispatched IS NULL AND outcome IS NULL
                 AND source = 'unknown')
                OR (status = 'succeeded' AND dispatched IS TRUE
                    AND outcome IS NOT DISTINCT FROM 'succeeded')
                OR (status = 'failed' AND (
                    (dispatched IS FALSE AND outcome IS NULL)
                    OR (dispatched IS TRUE AND outcome IS NOT NULL
                        AND outcome <> 'succeeded')
                ))
            ),
            CHECK (
                source = 'unknown'
                OR (mode = 'simulated' AND source = 'simulated')
                OR (mode = 'live' AND source IN ('estimated', 'provider_reported'))
            )
        )
    """)
    op.execute("""
        CREATE INDEX inference_attempt_usage_idx
        ON inference_attempt (tenant_id, mode, created_at)
    """)


def downgrade() -> None:
    op.drop_table("inference_attempt")
