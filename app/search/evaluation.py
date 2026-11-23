from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.snapshot import ContentSnapshot
from app.db.models import EvaluationCase
from app.search.hybrid import InMemoryHybridSearch


def _chunk_link_keys(metadata: dict[str, object]) -> list[str]:
    value = metadata.get("link_keys", [])
    if not isinstance(value, list):
        return []
    return [key for key in value if isinstance(key, str)]


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    valid: bool
    retrieval_hit_rate: float
    link_hit_rate: float
    off_topic_refusal_rate: float
    wrong_refusal_rate: float
    details: dict[str, object]
    publishable: bool


class Evaluator:
    async def evaluate(
        self,
        session: AsyncSession,
        snapshot: ContentSnapshot,
        query_vectors: dict[str, tuple[float, ...]],
        *,
        retrieval_min_hit: float,
        link_min_hit: float,
        off_topic_min_refusal: float,
        wrong_refusal_max: float,
        vector_min: float,
        bm25_min: float,
    ) -> EvaluationReport:
        cases = (
            await session.scalars(select(EvaluationCase).where(EvaluationCase.active.is_(True)))
        ).all()
        search = InMemoryHybridSearch(snapshot)
        hit_total = 0
        link_total = 0
        eligible = 0
        off_topic = 0
        refused_off_topic = 0
        wrong_refusal = 0
        details: list[dict[str, object]] = []

        for case in cases:
            expect = case.expect if isinstance(case.expect, dict) else {}
            tags = set(case.tags or [])
            vector = query_vectors.get(case.question)
            hits, gate = search.retrieve(vector, case.question, limit=10)
            chunk_keys = [hit.chunk_key for hit in hits[:3]]
            expected_chunks = expect.get("chunk_keys")
            expected_links = expect.get("link_keys")
            best_vector_value = gate["best_vector"]
            best_bm25_value = gate["best_bm25"]
            best_vector = (
                float(best_vector_value) if isinstance(best_vector_value, int | float) else 0.0
            )
            best_bm25 = float(best_bm25_value) if isinstance(best_bm25_value, int | float) else 0.0

            if "off_topic" in tags or "injection" in tags:
                off_topic += 1
                if best_vector < vector_min and best_bm25 < bm25_min:
                    refused_off_topic += 1
                details.append(
                    {
                        "question": case.question,
                        "kind": "refusal",
                        "refused": best_vector < vector_min and best_bm25 < bm25_min,
                    }
                )
                continue

            eligible += 1
            chunk_hit = bool(
                isinstance(expected_chunks, list)
                and any(isinstance(key, str) and key in chunk_keys for key in expected_chunks)
            )
            link_hit = False
            if isinstance(expected_links, list):
                expected_link_keys = [key for key in expected_links if isinstance(key, str)]
                link_keys = {
                    key
                    for chunk in snapshot.chunks
                    if chunk.chunk_key in chunk_keys
                    for key in _chunk_link_keys(chunk.metadata)
                    if isinstance(key, str)
                }
                link_hit = bool(set(expected_link_keys).intersection(link_keys))
            hit_total += int(chunk_hit)
            link_total += int(link_hit)
            if best_vector < vector_min and best_bm25 < bm25_min:
                wrong_refusal += 1
            details.append(
                {
                    "question": case.question,
                    "chunk_hit": chunk_hit,
                    "link_hit": link_hit,
                    "top_chunk_keys": chunk_keys,
                }
            )

        retrieval_hit_rate = hit_total / eligible if eligible else 1.0
        link_hit_rate = link_total / eligible if eligible else 1.0
        off_topic_refusal_rate = refused_off_topic / off_topic if off_topic else 1.0
        wrong_refusal_rate = wrong_refusal / eligible if eligible else 0.0
        valid = (
            retrieval_hit_rate >= retrieval_min_hit
            and link_hit_rate >= link_min_hit
            and off_topic_refusal_rate >= off_topic_min_refusal
            and wrong_refusal_rate <= wrong_refusal_max
        )
        return EvaluationReport(
            valid=valid,
            retrieval_hit_rate=retrieval_hit_rate,
            link_hit_rate=link_hit_rate,
            off_topic_refusal_rate=off_topic_refusal_rate,
            wrong_refusal_rate=wrong_refusal_rate,
            details={"cases": details},
            publishable=valid,
        )
