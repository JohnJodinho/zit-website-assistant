"""Add Phase 2 content aliases and idempotent write records."""

from alembic import op

revision = "0002_phase2_content"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE assistant.documents ADD COLUMN aliases text[] NOT NULL DEFAULT '{}'")
    op.execute(
        """
        CREATE TABLE assistant.idempotency_records (
            key_hash text PRIMARY KEY,
            actor_id uuid NOT NULL REFERENCES assistant.api_keys(id) ON DELETE CASCADE,
            method text NOT NULL,
            route text NOT NULL,
            request_hash text NOT NULL,
            response jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX idempotency_records_expires_at_idx "
        "ON assistant.idempotency_records (expires_at)"
    )
    op.execute(
        "UPDATE assistant.ingestion_runs "
        "SET status = 'interrupted', finished_at = now() WHERE status = 'running'"
    )
    op.execute(
        "CREATE UNIQUE INDEX one_running_ingestion "
        "ON assistant.ingestion_runs ((status)) WHERE status = 'running'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX assistant.one_running_ingestion")
    op.execute("DROP INDEX assistant.idempotency_records_expires_at_idx")
    op.execute("DROP TABLE assistant.idempotency_records")
    op.execute("ALTER TABLE assistant.documents DROP COLUMN aliases")
