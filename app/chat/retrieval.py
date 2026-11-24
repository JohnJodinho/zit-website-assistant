from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

from fastapi import Request

from app.api.deps import get_embedding_client
from app.chat.prompt import build_prompt
from app.config import Settings
from app.content.snapshot import ContentSnapshot, SnapshotChunk, SnapshotLink
from app.embeddings.client import EmbeddingServiceError
from app.obs.logging import get_logger
from app.search.hybrid import InMemoryHybridSearch, SearchHit
from app.search.intent import detect_intents

_NOT_SURE = (
    "I'm not sure based on the information available. Please contact ZIT Admissions for help."
)
_INJECTION_REFUSAL = "I can only help with accurate information about ZIT and its services."
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class ChatPlan:
    path: str
    intent: tuple[str, ...]
    answer: str | None
    prompt: str | None
    links: tuple[SnapshotLink, ...]
    hits: tuple[SearchHit, ...]
    degraded: bool
    confidence: dict[str, float]


async def prepare_chat_plan(
    request: Request,
    question: str,
    snapshot: ContentSnapshot | None,
) -> ChatPlan:
    settings: Settings = request.app.state.settings
    intents = detect_intents(question)
    if "injection" in intents:
        return _direct_plan("refusal", _INJECTION_REFUSAL, intents)
    if snapshot is None:
        return _direct_plan("not_sure", _NOT_SURE, intents, degraded=True)

    entity = _match_entity(question, snapshot)
    fast = _fast_response(question, intents, entity, snapshot, settings)
    if fast is not None:
        return fast

    vector = await _query_vector(request, question)
    search = InMemoryHybridSearch(snapshot)
    hits, gate = search.retrieve(vector, question, limit=8)
    best_vector = _float_value(gate.get("best_vector"))
    best_bm25 = _float_value(gate.get("best_bm25"))
    bm25_min = settings.gate_bm25_min_degraded if vector is None else settings.gate_bm25_min
    if best_vector < settings.gate_vector_min and best_bm25 < bm25_min:
        return _direct_plan(
            "not_sure",
            _NOT_SURE,
            intents,
            degraded=vector is None,
            confidence={"vector": best_vector, "bm25": best_bm25},
        )

    top_hits = tuple(hits[:5])
    links = _links_for_hits(snapshot, top_hits)
    if settings.fast_faq and top_hits and top_hits[0].doc_key.startswith("faq:"):
        faq_answer = top_hits[0].text
        return ChatPlan(
            path="faq_direct",
            intent=tuple(sorted(intents)),
            answer=faq_answer,
            prompt=None,
            links=links,
            hits=top_hits,
            degraded=vector is None,
            confidence={"vector": best_vector, "bm25": best_bm25},
        )

    return ChatPlan(
        path="retrieval",
        intent=tuple(sorted(intents)),
        answer=None,
        prompt=build_prompt(question, top_hits, links),
        links=links,
        hits=top_hits,
        degraded=vector is None,
        confidence={"vector": best_vector, "bm25": best_bm25},
    )


def _fast_response(
    question: str,
    intents: frozenset[str],
    entity: tuple[str, str] | None,
    snapshot: ContentSnapshot,
    settings: Settings,
) -> ChatPlan | None:
    if settings.fast_greeting and "greeting" in intents:
        return _direct_plan(
            "greeting",
            "Hello! I can help with ZIT courses, fees, duration, and applications.",
            intents,
        )
    if settings.fast_thanks_bye and "thanks_bye" in intents:
        return _direct_plan(
            "thanks_bye",
            "You're welcome. Let me know if I can help with ZIT information.",
            intents,
        )
    if settings.fast_contact and "contact" in intents:
        return _contact_plan(intents, snapshot)
    if settings.fast_apply and "apply" in intents:
        if entity is None:
            return _direct_plan(
                "clarify",
                "Which ZIT course would you like to apply for?",
                intents,
            )
        link = _entity_link(snapshot, entity[0], "apply")
        if link is not None:
            return ChatPlan(
                path="apply",
                intent=tuple(sorted(intents)),
                answer=f"You can apply for {entity[1]} here: [{link.label}]({link.url})",
                prompt=None,
                links=(link,),
                hits=(),
                degraded=False,
                confidence={},
            )
    if settings.fast_field and entity is not None:
        field = _field_for_intent(intents)
        if field is not None:
            chunk = _entity_chunk(snapshot, entity[0], field)
            if chunk is not None:
                value = chunk.metadata.get(field)
                if isinstance(value, str) and value.strip():
                    answer = f"{entity[1]} — {field.replace('_', ' ')}: {value.strip()}."
                    if field == "tuition":
                        answer += " This is as of the release date; please confirm with Admissions."
                    return ChatPlan(
                        path="field_lookup",
                        intent=tuple(sorted(intents)),
                        answer=answer,
                        prompt=None,
                        links=_links_for_hits(
                            snapshot,
                            (
                                SearchHit(
                                    chunk_key=chunk.chunk_key,
                                    doc_key=chunk.doc_key,
                                    score=1.0,
                                    text=chunk.text,
                                    vector_score=1.0,
                                    bm25_score=0.0,
                                ),
                            ),
                        ),
                        hits=(),
                        degraded=False,
                        confidence={"entity": 1.0},
                    )
    if settings.fast_category and "list_courses" in intents:
        return _category_response(question, intents, snapshot)
    return None


def _match_entity(
    question: str,
    snapshot: ContentSnapshot,
) -> tuple[str, str] | None:
    normalized_question = " ".join(_TOKEN.findall(question.casefold()))
    matches: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for chunk in snapshot.chunks:
        entity = chunk.metadata.get("entity")
        if not isinstance(entity, dict) or entity.get("type") != "course":
            continue
        key = entity.get("key")
        names = entity.get("names")
        if not isinstance(key, str) or not isinstance(names, list) or key in seen:
            continue
        seen.add(key)
        title = chunk.metadata.get("title")
        display_name = title if isinstance(title, str) else key.removeprefix("course:")
        for name in names:
            if not isinstance(name, str):
                continue
            normalized_name = " ".join(_TOKEN.findall(name.casefold()))
            if len(normalized_name) >= 4 and normalized_name in normalized_question:
                matches.append((len(normalized_name), key, display_name))
    if not matches:
        return None
    longest = max(length for length, _, _ in matches)
    best = {(key, name) for length, key, name in matches if length == longest}
    return next(iter(best)) if len(best) == 1 else None


def _field_for_intent(intents: frozenset[str]) -> str | None:
    for intent, field in (
        ("fee", "tuition"),
        ("duration", "duration"),
        ("requirements", "entry_requirements"),
        ("scholarship", "tuition"),
    ):
        if intent in intents:
            return field
    return None


def _entity_chunk(
    snapshot: ContentSnapshot,
    entity_key: str,
    field: str,
) -> SnapshotChunk | None:
    for chunk in snapshot.chunks:
        entity = chunk.metadata.get("entity")
        if (
            chunk.kind == "course_facts"
            and isinstance(entity, dict)
            and entity.get("key") == entity_key
            and isinstance(chunk.metadata.get(field), str)
        ):
            return chunk
    return None


def _entity_link(
    snapshot: ContentSnapshot,
    entity_key: str,
    action: str,
) -> SnapshotLink | None:
    suffix = entity_key.removeprefix("course:")
    link_key = f"{action}:{suffix}"
    return next((link for link in snapshot.links if link.link_key == link_key), None)


def _category_response(
    question: str,
    intents: frozenset[str],
    snapshot: ContentSnapshot,
) -> ChatPlan:
    query = " ".join(_TOKEN.findall(question.casefold()))
    matches: dict[str, str] = {}
    for chunk in snapshot.chunks:
        category = chunk.metadata.get("category")
        title = chunk.metadata.get("title")
        if (
            chunk.kind == "course_facts"
            and isinstance(category, str)
            and isinstance(title, str)
            and " ".join(_TOKEN.findall(category.casefold())) in query
        ):
            matches[chunk.doc_key] = title
    if not matches:
        return _direct_plan("clarify", "Which course category are you interested in?", intents)
    names = sorted(matches.values())[:10]
    return _direct_plan(
        "category",
        "Courses in that category include: " + ", ".join(names) + ".",
        intents,
    )


def _contact_plan(
    intents: frozenset[str],
    snapshot: ContentSnapshot,
) -> ChatPlan:
    link = next((item for item in snapshot.links if item.link_key == "contact:admissions"), None)
    if link is None:
        return _direct_plan("contact", "Please contact ZIT Admissions for assistance.", intents)
    return ChatPlan(
        path="contact",
        intent=tuple(sorted(intents)),
        answer=f"Please contact ZIT Admissions here: [{link.label}]({link.url})",
        prompt=None,
        links=(link,),
        hits=(),
        degraded=False,
        confidence={},
    )


def _links_for_hits(
    snapshot: ContentSnapshot,
    hits: tuple[SearchHit, ...],
) -> tuple[SnapshotLink, ...]:
    keys: set[str] = set()
    for hit in hits:
        chunk = next((item for item in snapshot.chunks if item.chunk_key == hit.chunk_key), None)
        if chunk is None:
            continue
        values = chunk.metadata.get("link_keys")
        if isinstance(values, list):
            keys.update(value for value in values if isinstance(value, str))
    return tuple(link for link in snapshot.links if link.link_key in keys)


async def _query_vector(request: Request, question: str) -> tuple[float, ...] | None:
    settings: Settings = request.app.state.settings
    if settings.zit_api_key is None:
        return None
    existing_cache = getattr(request.app.state, "query_embedding_cache", None)
    if isinstance(existing_cache, OrderedDict):
        cache: OrderedDict[str, tuple[float, tuple[float, ...]]] = existing_cache
    else:
        cache = OrderedDict()
        request.app.state.query_embedding_cache = cache
    key = hashlib.sha256(question.encode("utf-8")).hexdigest()
    now = monotonic()
    cached = cache.get(key)
    if cached is not None:
        created_at, vector = cached
        if now - created_at <= settings.session_cache_seconds:
            cache.move_to_end(key)
            return vector
        del cache[key]
    try:
        vectors = await get_embedding_client(request).embed_texts(
            [question],
            input_type="query",
        )
    except EmbeddingServiceError as exc:
        get_logger("chat.search", settings).warning(
            "query_embedding_failed",
            error_type=type(exc).__name__,
        )
        return None
    vector = tuple(vectors[0])
    cache[key] = (now, vector)
    while len(cache) > 512:
        cache.popitem(last=False)
    return vector


def _direct_plan(
    path: str,
    answer: str,
    intents: frozenset[str],
    *,
    degraded: bool = False,
    confidence: dict[str, float] | None = None,
) -> ChatPlan:
    return ChatPlan(
        path=path,
        intent=tuple(sorted(intents)),
        answer=answer,
        prompt=None,
        links=(),
        hits=(),
        degraded=degraded,
        confidence=confidence or {},
    )


def _float_value(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0
