from __future__ import annotations

from app.chat.cache import AnswerCache


def test_answer_cache_requires_same_release_and_retrieved_context() -> None:
    cache = AnswerCache()
    cache.put(
        "Course fees?",
        "Please confirm with Admissions.",
        2,
        (1.0, 0.0),
        frozenset({"fees"}),
        30,
    )

    assert cache.get(
        " COURSE   FEES? ",
        (1.0, 0.0),
        2,
        frozenset({"fees"}),
    ) == cache.get("course fees?", None, 2, frozenset({"fees"}))
    assert cache.get("Course fees?", (1.0, 0.0), 3, frozenset({"fees"})) is None
    assert cache.get("Course fees?", (1.0, 0.0), 2, frozenset({"duration"})) is None


def test_answer_cache_semantic_match_is_confined_to_same_release_context() -> None:
    cache = AnswerCache()
    cache.put(
        "What are the fees?",
        "Confirm fees with Admissions.",
        4,
        (1.0, 0.0),
        frozenset({"fees"}),
        30,
    )

    result = cache.get(
        "How much does it cost?",
        (0.999, 0.01),
        4,
        frozenset({"fees"}),
    )

    assert result is not None
    assert result.match == "cache_semantic"
    assert result.answer == "Confirm fees with Admissions."


def test_answer_cache_expires_entries_and_can_be_purged(monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setattr("app.chat.cache.monotonic", lambda: now[0])
    cache = AnswerCache()
    cache.put("Course fees?", "answer", 1, None, frozenset({"fees"}), 5)

    assert cache.get("Course fees?", None, 1, frozenset({"fees"})) is not None
    now[0] = 5.0
    assert cache.get("Course fees?", None, 1, frozenset({"fees"})) is None

    cache.put("Course fees?", "answer", 1, None, frozenset({"fees"}), 5)
    cache.clear()
    assert cache.get("Course fees?", None, 1, frozenset({"fees"})) is None
