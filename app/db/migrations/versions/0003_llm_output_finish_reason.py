"""Persist LLM output limits and provider finish reasons."""

from alembic import op

revision = "0003_llm_output_finish_reason"
down_revision = "0002_phase2_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE assistant.llm_calls ADD COLUMN max_output_tokens integer")
    op.execute("ALTER TABLE assistant.llm_calls ADD COLUMN finish_reason text")
    op.execute("CREATE INDEX llm_calls_trace_id_idx ON assistant.llm_calls (trace_id)")


def downgrade() -> None:
    op.execute("DROP INDEX assistant.llm_calls_trace_id_idx")
    op.execute("ALTER TABLE assistant.llm_calls DROP COLUMN finish_reason")
    op.execute("ALTER TABLE assistant.llm_calls DROP COLUMN max_output_tokens")
