from __future__ import annotations

import asyncio

from app.config import get_settings
from app.content.snapshot import load_active_snapshot
from app.db.models import EvaluationCase
from app.db.session import create_database_engine, create_session_factory
from app.search.evaluation import Evaluator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError


async def check() -> int:
    settings = get_settings()
    engine = create_database_engine(settings)
    if engine is None:
        print("SEARCH FAIL\tDATABASE_URL missing")
        return 1

    try:
        async with create_session_factory(engine)() as session:
            snapshot = await load_active_snapshot(session, settings)
            if snapshot is None:
                print("SEARCH FAIL\tno validated active release")
                return 1

            cases = (
                await session.scalars(select(EvaluationCase).where(EvaluationCase.active.is_(True)))
            ).all()
            missing = [
                case for case in cases if case.embedding is None or len(case.embedding) != 768
            ]
            if missing:
                print(f"SEARCH FAIL\t{len(missing)} query embeddings missing")
                return 1

            query_vectors = {
                case.question: tuple(float(value) for value in case.embedding or ())
                for case in cases
            }
            report = await Evaluator().evaluate(
                session,
                snapshot,
                query_vectors,
                retrieval_min_hit=settings.gate_retrieval_min_hit,
                link_min_hit=0.95,
                off_topic_min_refusal=0.95,
                wrong_refusal_max=0.05,
                vector_min=settings.gate_vector_min,
                bm25_min=settings.gate_bm25_min,
            )
            detail_rows = report.details.get("cases")
            if not isinstance(detail_rows, list):
                print("SEARCH FAIL\tmalformed evaluation details")
                return 1
            results = {
                str(item["question"]): item
                for item in detail_rows
                if isinstance(item, dict) and isinstance(item.get("question"), str)
            }
            automatic = [case for case in cases if "automatic" in (case.tags or [])]
            handwritten = [case for case in cases if "handwritten" in (case.tags or [])]
            adversarial = [
                case for case in cases if {"off_topic", "injection"}.intersection(case.tags or [])
            ]
            automatic_hits = sum(
                bool(results.get(case.question, {}).get("chunk_hit")) for case in automatic
            )
            automatic_link_hits = sum(
                bool(results.get(case.question, {}).get("link_hit")) for case in automatic
            )
            handwritten_hits = sum(
                bool(results.get(case.question, {}).get("chunk_hit")) for case in handwritten
            )
            refusals = sum(
                bool(results.get(case.question, {}).get("refused")) for case in adversarial
            )
            rates = {
                "release_id": snapshot.release_id,
                "automatic_top3": _rate(automatic_hits, len(automatic)),
                "automatic_link": _rate(automatic_link_hits, len(automatic)),
                "handwritten_top3": _rate(handwritten_hits, len(handwritten)),
                "off_topic_injection_refusal": _rate(refusals, len(adversarial)),
                "wrong_refusal": report.wrong_refusal_rate,
            }
            valid = (
                rates["automatic_top3"] >= 0.95
                and rates["automatic_link"] >= 0.95
                and rates["handwritten_top3"] >= 0.90
                and rates["off_topic_injection_refusal"] >= 0.95
                and rates["wrong_refusal"] <= 0.05
            )
            print(f"SEARCH {'PASS' if valid else 'FAIL'}\t{rates}")
            return 0 if valid else 1
    except SQLAlchemyError as exc:
        print(f"SEARCH FAIL\tdatabase error ({type(exc).__name__})")
        return 1
    finally:
        await engine.dispose()


def _rate(hits: int, total: int) -> float:
    return hits / total if total else 0.0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))
