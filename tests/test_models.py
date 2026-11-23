import app.db.models  # noqa: F401
from app.db.base import Base


def test_orm_metadata_covers_the_foundation_schema() -> None:
    expected_tables = {
        "assistant.api_keys",
        "assistant.audit_log",
        "assistant.chunks",
        "assistant.documents",
        "assistant.error_events",
        "assistant.eval_cases",
        "assistant.eval_runs",
        "assistant.ingestion_events",
        "assistant.ingestion_runs",
        "assistant.idempotency_records",
        "assistant.links",
        "assistant.llm_calls",
        "assistant.release_chunks",
        "assistant.release_links",
        "assistant.releases",
        "assistant.sessions",
        "assistant.settings",
        "assistant.sources",
        "assistant.spans",
        "assistant.suppressions",
        "assistant.traces",
    }

    assert set(Base.metadata.tables) == expected_tables
