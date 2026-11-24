from __future__ import annotations

from app.chat.cache import AnswerCache


def test_answer_cache_hits_only_exact_normalized_question_and_release() -> None:
    cache = AnswerCache()
    cache.put("Course fees?", "Please confirm with Admissions.", 2, 30)

    match = cache.get(" COURSE   FEES? ", 2)

    assert match is not None
    assert match.path == "cache_exact"
    assert match.answer == "Please confirm with Admissions."
    assert cache.get("Course fees?", 3) is None
    assert cache.get("Course duration?", 2) is None


def test_answer_cache_expires_entries_and_can_be_purged(monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setattr("app.chat.cache.monotonic", lambda: now[0])
    cache = AnswerCache()
    cache.put("Course fees?", "answer", 1, 5)

    assert cache.get("Course fees?", 1) is not None
    now[0] = 5.0
    assert cache.get("Course fees?", 1) is None

    cache.put("Course fees?", "answer", 1, 5)
    cache.clear()
    assert cache.get("Course fees?", 1) is None
