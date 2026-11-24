from __future__ import annotations

from types import SimpleNamespace

from app.chat.retrieval import prepare_chat_plan
from app.config import Settings
from app.content.snapshot import ContentSnapshot, SnapshotChunk


async def test_drill_2_five_synthetic_faqs_take_the_direct_answer_path(monkeypatch) -> None:
    questions = tuple(f"What does ZIT FAQ number {index} recommend?" for index in range(5))
    vectors = {
        question: tuple(1.0 if position == index else 0.0 for position in range(768))
        for index, question in enumerate(questions)
    }
    chunks = tuple(
        SnapshotChunk(
            id=f"zzdrill-{index}",
            chunk_key=f"zzdrill-faq-{index}",
            doc_key=f"faq:zzdrill-{index}",
            kind="faq",
            text=f"Synthetic answer number {index}.",
            embed_text=question,
            token_count=12,
            metadata={"faq": {"question": question}},
            embedding=vectors[question],
        )
        for index, question in enumerate(questions)
    )
    snapshot = ContentSnapshot(
        release_id=1,
        chunks=chunks,
        links=(),
        loaded_at="drill",
    )
    settings = Settings(
        _env_file=None,
        fast_faq=True,
        gate_vector_min=0.1,
        gate_bm25_min=0.0,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))

    async def embed_query(_request: object, question: str) -> tuple[float, ...]:
        return vectors[question]

    monkeypatch.setattr("app.chat.retrieval._query_vector", embed_query)

    answers = []
    for index, question in enumerate(questions):
        plan = await prepare_chat_plan(request, question, snapshot)
        assert plan.path == "faq_direct"
        assert plan.answer == f"Synthetic answer number {index}."
        answers.append(plan.answer)

    assert len(set(answers)) == 5
