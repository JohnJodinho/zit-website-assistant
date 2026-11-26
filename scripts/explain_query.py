from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chat.models import eligible_models
from app.chat.pii import mask_pii
from app.chat.retrieval import (
    ChatPlan,
    _entity_chunk,
    _entity_link,
    _field_for_intent,
    _match_entity,
    prepare_chat_plan,
)
from app.config import Settings
from app.content.snapshot import ContentSnapshot, load_active_snapshot
from app.db.session import create_database_engine
from app.embeddings.client import BgeEmbeddingClient
from app.search.hybrid import InMemoryHybridSearch
from app.search.intent import INTENT_PATTERNS, detect_intents
from fastapi import FastAPI, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CASE_STUDY_MESSAGES = (
    "Helllo",
    "Hello",
    "hello",
    "Hellooo",
    "Hi",
    "hii",
    "hey there",
    "Good morning",
    "thanks",
    "thank you!!",
)
Result = dict[str, Any]


async def load_snapshot_read_only(settings: Settings) -> ContentSnapshot | None:
    engine = create_database_engine(settings)
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured; cannot load the active snapshot.")
    try:
        async with engine.connect() as connection, connection.begin():
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                snapshot = await load_active_snapshot(session, settings)
        return snapshot
    finally:
        await engine.dispose()


def build_request(settings: Settings, snapshot: ContentSnapshot | None) -> tuple[FastAPI, Request]:
    application = FastAPI()
    application.state.settings = settings
    application.state.active_snapshot = snapshot
    application.state.query_embedding_cache = OrderedDict()
    application.state.embedding_client = (
        BgeEmbeddingClient(settings, max_attempts=1)
        if settings.zit_api_key is not None
        else None
    )
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/chat/stream",
        "raw_path": b"/api/v1/chat/stream",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 8000),
        "app": application,
    }
    return application, Request(scope)


def explain_fast_paths(
    plan: ChatPlan,
    settings: Settings,
    intents: frozenset[str],
    entity: tuple[str, str] | None,
    snapshot: ContentSnapshot | None,
) -> list[str]:
    if "injection" in intents:
        return ["All fast paths: not reached; the injection refusal branch returned first."]
    if snapshot is None:
        return ["All fast paths: not reached; the missing-snapshot branch returned first."]

    explanations: list[str] = []
    returned = False

    def check(
        name: str,
        enabled: bool,
        intent: str,
        condition: bool,
        missing: str,
    ) -> None:
        nonlocal returned
        if returned:
            explanations.append(f"{name}: not reached; an earlier fast path returned.")
        elif not enabled:
            explanations.append(f"{name}: disabled by its FAST flag.")
        elif intent not in intents:
            explanations.append(f"{name}: intent rule did not match ({intent}).")
        elif not condition:
            explanations.append(f"{name}: intent matched, but {missing}.")
        else:
            explanations.append(f"{name}: matched; selected path '{plan.path}'.")
            returned = True

    check("greeting", settings.fast_greeting, "greeting", True, "")
    check("thanks/bye", settings.fast_thanks_bye, "thanks_bye", True, "")
    check(
        "contact",
        settings.fast_contact,
        "contact",
        True,
        "",
    )

    apply_condition = False
    apply_missing = "no course entity was matched"
    if entity is not None and snapshot is not None:
        apply_condition = _entity_link(snapshot, entity[0], "apply") is not None
        apply_missing = "the matched course has no approved apply link"
    check(
        "apply",
        settings.fast_apply,
        "apply",
        apply_condition or entity is None,
        apply_missing,
    )
    if explanations[-1].startswith("apply: matched"):
        if entity is None:
            explanations[-1] = (
                "apply: intent matched without a course entity; "
                "returned path 'clarify'."
            )
        elif plan.path != "apply":
            explanations[-1] = (
                "apply: matched, but no approved apply link was available; code continued."
            )
            returned = False

    field_intent = _field_for_intent(intents)
    field_rule = next(
        (
            intent
            for intent in ("fee", "duration", "requirements", "scholarship")
            if intent in intents
        ),
        None,
    )
    field_available = False
    field_missing = "no course entity was matched"
    if entity is not None:
        field_missing = "no supported field intent was matched"
    if entity is not None and field_intent is not None and snapshot is not None:
        chunk = _entity_chunk(snapshot, entity[0], field_intent)
        value = chunk.metadata.get(field_intent) if chunk is not None else None
        field_available = isinstance(value, str) and bool(value.strip())
        field_missing = f"the entity has no usable '{field_intent}' field"
    check(
        "field lookup",
        settings.fast_field,
        field_rule or "fee/duration/requirements/scholarship",
        field_available,
        field_missing,
    )
    check(
        "category/list",
        settings.fast_category,
        "list_courses",
        True,
        "",
    )
    if returned:
        explanations.append("FAQ direct: not reached; an earlier fast path returned.")
    elif not settings.fast_faq:
        explanations.append("FAQ direct: disabled by its FAST flag.")
    elif plan.path == "faq_direct":
        explanations.append("FAQ direct: top gated search result is an FAQ; returned that text.")
    elif plan.path == "not_sure":
        explanations.append("FAQ direct: not reached; search did not pass the relevance gate.")
    else:
        explanations.append("FAQ direct: search passed, but the top result is not an FAQ.")
    return explanations


async def explain_one(
    request: Request,
    settings: Settings,
    snapshot: ContentSnapshot | None,
    message: str,
) -> Result:
    masked, found_pii = mask_pii(message)
    intents = detect_intents(masked)
    entity = _match_entity(masked, snapshot) if snapshot is not None else None
    plan = await prepare_chat_plan(request, masked, snapshot)
    search_ran = "vector" in plan.confidence or "bm25" in plan.confidence

    hits: list[dict[str, object]] = []
    gate: dict[str, object] | None = None
    query_vector: tuple[float, ...] | None = None
    embedding_mode = "not searched"
    if search_ran and snapshot is not None:
        cache_key = hashlib.sha256(masked.encode("utf-8")).hexdigest()
        cached_embedding = request.app.state.query_embedding_cache.get(cache_key)
        query_vector = cached_embedding[1] if cached_embedding is not None else None
        if query_vector is not None:
            embedding_mode = "dense vector plus BM25"
        elif settings.zit_api_key is None:
            embedding_mode = "BM25 only; embedding credentials are not configured"
        else:
            embedding_mode = "BM25 only; the embedding service returned no vector"
        search_hits, gate = InMemoryHybridSearch(snapshot).retrieve(
            query_vector,
            masked,
            limit=8,
        )
        chunks = {chunk.chunk_key: chunk for chunk in snapshot.chunks}
        hits = [
            {
                "chunk_key": hit.chunk_key,
                "doc_key": hit.doc_key,
                "title": chunks[hit.chunk_key].metadata.get("title", hit.doc_key),
                "rrf_score": round(hit.score, 6),
                "vector_score": round(hit.vector_score, 6),
                "bm25_score": round(hit.bm25_score, 6),
            }
            for hit in search_hits[:5]
        ]

    bm25_threshold = (
        settings.gate_bm25_min_degraded
        if plan.degraded
        else settings.gate_bm25_min
    )
    gate_passed: bool | None = None
    if gate is not None:
        best_vector = float(gate["best_vector"])
        best_bm25 = float(gate["best_bm25"])
        gate_passed = not (
            best_vector < settings.gate_vector_min
            and best_bm25 < bm25_threshold
        )

    if plan.answer is not None:
        answer_source = "fixed backend reply"
        final_answer = plan.answer
    else:
        configured_models = eligible_models(settings.llm_models)
        provider_key_available = any(
            (model.provider == "groq" and settings.groq_api_key is not None)
            or (model.provider == "gemini" and settings.google_ai_api_key is not None)
            for model in configured_models
        )
        if configured_models and provider_key_available:
            answer_source = "language model would be called; this script never calls it"
            final_answer = (
                f"A language model would receive {len(plan.hits)} retrieved chunks. "
                "Runtime quota admission is not simulated."
            )
        else:
            answer_source = "capacity fallback would be returned; this script never calls a model"
            final_answer = "Please contact ZIT Admissions for help with this question."

    rules = {
        intent: INTENT_PATTERNS[intent].pattern
        for intent in sorted(intents)
    }
    return {
        "message": message,
        "masked_text": masked,
        "pii_types_masked": found_pii,
        "intents": sorted(intents),
        "matched_intent_rules": rules,
        "entity_match": (
            {"key": entity[0], "display_name": entity[1]} if entity is not None else None
        ),
        "pre_fast_path_checks": [
            f"injection refusal: {'matched' if 'injection' in intents else 'not matched'}",
            f"active snapshot: {'loaded' if snapshot is not None else 'missing'}",
        ],
        "fast_path_checks": explain_fast_paths(plan, settings, intents, entity, snapshot),
        "search": {
            "ran": search_ran,
            "degraded": plan.degraded if search_ran else None,
            "mode": embedding_mode,
            "gate": gate,
            "vector_threshold": settings.gate_vector_min if search_ran else None,
            "bm25_threshold": bm25_threshold if search_ran else None,
            "gate_passed": gate_passed,
            "top_results": hits,
            "faq_direct_enabled": settings.fast_faq,
            "faq_direct_selected": plan.path == "faq_direct",
        },
        "path": plan.path,
        "answer_source": answer_source,
        "answer": final_answer,
        "snapshot_release_id": snapshot.release_id if snapshot is not None else None,
        "conversation_history_supported": False,
    }


def print_result(result: Result) -> None:
    print(f"Message: {result['message']}")
    print(f"Masked text: {result['masked_text']}")
    print(f"PII types masked: {result['pii_types_masked'] or 'none'}")
    print(f"Intents: {result['intents'] or 'none'}")
    for intent, rule in result["matched_intent_rules"].items():
        print(f"  Rule for {intent}: {rule}")
    print("Pre-fast-path checks:")
    for check_line in result["pre_fast_path_checks"]:
        print(f"  - {check_line}")
    print("Fast-path checks:")
    for check_line in result["fast_path_checks"]:
        print(f"  - {check_line}")
    search = result["search"]
    print(f"Search ran: {search['ran']}")
    if search["ran"]:
        print(f"Search degraded: {search['degraded']}")
        print(f"Search mode: {search['mode']}")
        print(f"Gate: {search['gate']}")
        print(f"Gate passed: {search['gate_passed']}")
        for hit in search["top_results"]:
            print(f"  - {hit}")
    print(f"Final path: {result['path']}")
    print(f"Answer source: {result['answer_source']}")
    print(f"Answer: {result['answer']}")
    print("Conversation history: unsupported; only the current message is evaluated.")


async def run(args: argparse.Namespace) -> int:
    settings = Settings()
    snapshot = await load_snapshot_read_only(settings)
    application, request = build_request(settings, snapshot)
    try:
        messages = CASE_STUDY_MESSAGES if args.case_study else (args.query,)
        results: list[Result] = [
            await explain_one(request, settings, snapshot, message)
            for message in messages
        ]
        if args.json:
            print(json.dumps(results if args.case_study else results[0], indent=2))
        else:
            if snapshot is None:
                print("No active content snapshot is loaded.")
            else:
                print(f"Loaded active release {snapshot.release_id} read-only.")
            for index, result in enumerate(results):
                if index:
                    print()
                print_result(result)
    finally:
        client = application.state.embedding_client
        if client is not None:
            await client.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explain the real chat decision path without calling a language model."
    )
    parser.add_argument("query", nargs="?", help="One visitor message to explain.")
    parser.add_argument(
        "--case-study",
        action="store_true",
        help="Run the ten greeting and small-talk examples from the architecture report.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()
    if not args.case_study and not args.query:
        parser.error("provide a query or use --case-study")
    if args.case_study and args.query:
        parser.error("do not combine a query with --case-study")
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        print(f"Could not explain the query: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
