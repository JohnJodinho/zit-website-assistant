from __future__ import annotations

from app.content.snapshot import ContentSnapshot, SnapshotChunk, SnapshotLink
from app.search.hybrid import InMemoryHybridSearch
from app.search.intent import detect_intents


def snapshot() -> ContentSnapshot:
    return ContentSnapshot(
        release_id=1,
        chunks=(
            SnapshotChunk(
                id="1",
                chunk_key="course:diploma-in-cybersecurity#facts",
                doc_key="course:diploma-in-cybersecurity",
                kind="course_facts",
                text="Diploma in Cybersecurity duration 12 months tuition 350000",
                embed_text="Diploma in Cybersecurity duration tuition",
                token_count=20,
                metadata={"link_keys": ["course:diploma-in-cybersecurity"]},
                embedding=(1.0,) + (0.0,) * 767,
            ),
        ),
        links=(
            SnapshotLink(
                link_key="course:diploma-in-cybersecurity",
                kind="course",
                label="Diploma in Cybersecurity",
                url="https://www.zibeh.ng/courses/diploma-in-cybersecurity",
                description="",
                aliases=("Cybersecurity",),
                priority=50,
            ),
        ),
        loaded_at="2026-11-23T00:00:00Z",
    )


def test_hybrid_search_finds_exact_chunk() -> None:
    search = InMemoryHybridSearch(snapshot())
    hits, gate = search.retrieve(
        (1.0,) + (0.0,) * 767,
        "How much is Diploma in Cybersecurity?",
    )
    assert hits
    assert hits[0].chunk_key == "course:diploma-in-cybersecurity#facts"
    assert gate["degraded"] is False


def test_degraded_search_does_not_rank_zero_score_chunks() -> None:
    current = snapshot()
    irrelevant = SnapshotChunk(
        id="2",
        chunk_key="page:contact",
        doc_key="page:contact",
        kind="page",
        text="Contact the admissions team for help.",
        embed_text="Contact admissions",
        token_count=5,
        metadata={},
        embedding=(0.0,) * 768,
    )
    search = InMemoryHybridSearch(
        ContentSnapshot(
            release_id=current.release_id,
            chunks=(*current.chunks, irrelevant),
            links=current.links,
            loaded_at=current.loaded_at,
        )
    )

    hits, gate = search.retrieve(None, "How much is Diploma in Cybersecurity?")

    assert [hit.chunk_key for hit in hits] == ["course:diploma-in-cybersecurity#facts"]
    assert gate["degraded"] is True


def test_bm25_gate_uses_normalized_query_coverage() -> None:
    search = InMemoryHybridSearch(snapshot())

    _, relevant = search.retrieve(None, "Diploma in Cybersecurity tuition")
    _, unrelated = search.retrieve(None, "Write a poem about the moon")

    assert relevant["best_bm25"] >= 0.3
    assert unrelated["best_bm25"] < 0.3


def test_intent_rules() -> None:
    intents = detect_intents("How do I apply for cybersecurity?")
    assert "apply" in intents
    assert "fee" not in intents
