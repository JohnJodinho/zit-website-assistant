from __future__ import annotations

from app.content.diff import ExistingChunk, check_diff_safety, diff_chunks
from app.content.models import ContentChunk


def _chunk(key: str, content_hash: str) -> ContentChunk:
    return ContentChunk(
        chunk_key=key,
        doc_key="doc",
        kind="summary",
        text=key,
        token_count=80,
        content_hash=content_hash,
        metadata={},
    )


def test_diff_preserves_manual_overrides_and_suppressions() -> None:
    result = diff_chunks(
        {
            "same": ExistingChunk("same-hash", "etl"),
            "changed": ExistingChunk("old-hash", "etl"),
            "override": ExistingChunk("manual-hash", "manual"),
            "removed": ExistingChunk("old", "etl"),
            "suppressed": ExistingChunk("old", "etl"),
        },
        [
            _chunk("same", "same-hash"),
            _chunk("changed", "new-hash"),
            _chunk("override", "etl-hash"),
            _chunk("new", "new-hash"),
            _chunk("suppressed", "new-hash"),
        ],
        {"suppressed"},
    )

    assert [item.chunk_key for item in result.added] == ["new"]
    assert [item.chunk_key for item in result.changed] == ["changed"]
    assert result.removed == ("removed", "suppressed")
    assert result.unchanged == ("same",)
    assert result.conflicts == ("override",)
    assert result.suppressed == ("suppressed",)


def test_diff_safety_enforces_thresholds_unless_force_is_enabled() -> None:
    result = check_diff_safety(
        existing_count=10,
        incoming_count=20,
        removal_count=3,
        max_removal_percent=15,
        max_count_swing_percent=50,
    )

    assert not result.allowed
    assert result.removal_percent == 30
    assert result.count_swing_percent == 100
    assert set(result.violations) == {"removal_limit_exceeded", "count_swing_limit_exceeded"}
    forced = check_diff_safety(
        existing_count=10,
        incoming_count=20,
        removal_count=3,
        max_removal_percent=15,
        max_count_swing_percent=50,
        force=True,
    )
    assert forced.allowed
    initial = check_diff_safety(
        existing_count=0,
        incoming_count=183,
        removal_count=0,
        max_removal_percent=15,
        max_count_swing_percent=50,
    )
    assert initial.allowed
