from __future__ import annotations

from app.search.intent import detect_intents
from scripts.seed_eval_cases import adversarial_cases, course_cases, handwritten_cases


def test_evaluation_sets_have_expected_counts_and_no_drill_tags() -> None:
    automatic = course_cases()
    handwritten = handwritten_cases()
    adversarial = adversarial_cases()

    assert len(automatic) == 135
    assert len(handwritten) == 40
    assert len(adversarial) == 40
    questions = [case["question"] for case in (*automatic, *handwritten, *adversarial)]
    assert len(questions) == len(set(questions))
    for case in (*automatic, *handwritten, *adversarial):
        assert not any(tag.startswith("zzdrill-") for tag in case["tags"])


def test_search_cases_have_expected_chunks_and_links() -> None:
    cases = (*course_cases(), *handwritten_cases())

    assert all(case["expect"]["chunk_keys"] for case in cases)
    assert all(case["expect"]["link_keys"] for case in cases)


def test_injection_cases_match_a_refusal_intent() -> None:
    cases = [case for case in adversarial_cases() if "injection" in case["tags"]]

    assert all("injection" in detect_intents(case["question"]) for case in cases)
