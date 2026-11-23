from __future__ import annotations

import csv
import json
import re
from datetime import date
from io import StringIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_scope
from app.content.idempotency import execute_idempotently
from app.content.models import ContentChunk
from app.content.provider import embed_documents
from app.content.repository import (
    active_release_id,
    add_audit_record,
    add_chunk_version,
    attach_chunk,
    ensure_draft,
    release_chunks,
    remove_chunk_from_release,
    validate_link_keys,
)
from app.content.schemas import FAQBulkRequest, FAQCreate, FAQPatch
from app.content.validation import ContentValidationError, build_manual_chunk
from app.db.models import Chunk, Document, Release, ReleaseChunk
from app.db.session import get_db_session
from app.security.keys import AdminPrincipal, AdminScope

router = APIRouter(prefix="/admin/v1", tags=["FAQs"])


@router.get("/faqs")
async def list_faqs(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
    due: bool = False,
    tag: str | None = None,
    limit: int = 50,
    before_key: str | None = None,
) -> dict[str, object]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="invalid_page_limit")
    release_id = await _current_release_id(session)
    if release_id is None:
        return {"items": [], "next_cursor": None}
    pairs = await _faq_pairs(session, release_id)
    today = date.today()
    items = [
        _faq_view(document, chunk)
        for document, chunk in pairs
        if _is_faq_due(chunk, today, due)
        and (tag is None or tag in _faq_metadata(chunk).get("tags", []))
        and (before_key is None or document.doc_key > before_key)
    ]
    page = items[:limit]
    return {
        "items": page,
        "next_cursor": page[-1]["id"] if len(items) > limit and page else None,
    }


@router.get("/faqs/{faq_id}")
async def get_faq(
    faq_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    doc_key = faq_id if faq_id.startswith("faq:") else f"faq:{faq_id}"
    release_id = await _current_release_id(session)
    if release_id is None:
        raise HTTPException(status_code=404, detail="faq_not_found")
    pair = await _faq_pair(session, release_id, doc_key)
    if pair is None:
        raise HTTPException(status_code=404, detail="faq_not_found")
    return _faq_view(*pair)


@router.post("/faqs", status_code=status.HTTP_201_CREATED)
async def create_faq(
    body: FAQCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    _reject_inline_publish(body.publish)
    candidate, metadata, faq_id = _faq_candidate(body, request)
    await _validate_faq_links(request, body.link_keys)
    vectors, model_id = await embed_documents(request, [candidate.embed_text or ""])

    async def mutation() -> dict[str, object]:
        draft = await ensure_draft(session, principal.name, "Create FAQ")
        if await session.get(Document, f"faq:{faq_id}") is not None:
            raise HTTPException(status_code=409, detail="faq_already_exists")
        await _check_faq_links(session, draft.id, body.link_keys)
        document = Document(
            doc_key=f"faq:{faq_id}",
            doc_type="faq",
            title=body.question,
            url_path=None,
            origin="manual",
            aliases=_unique_values(body.variants),
            status="active",
        )
        session.add(document)
        await session.flush()
        chunk = await add_chunk_version(
            session,
            candidate,
            actor=principal.name,
            origin="manual",
            embedding=vectors[0],
            embedding_model=model_id,
        )
        await attach_chunk(session, draft.id, chunk)
        add_audit_record(
            session,
            actor=principal.name,
            action="faq.create",
            target=f"faq:{faq_id}",
            before=None,
            after={"content_hash": chunk.content_hash, "faq": metadata},
            trace_id=request.state.trace_id,
        )
        return {"id": faq_id, "document": _faq_view(document, chunk)}

    return await execute_idempotently(
        session,
        request,
        principal,
        body.model_dump(mode="json"),
        mutation,
    )


@router.post("/faqs/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_create_faqs(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    body, row_errors = await _parse_bulk(request)
    if row_errors and not body.partial:
        raise HTTPException(
            status_code=422,
            detail={"code": "bulk_validation_failed", "rows": row_errors},
        )
    valid_items = body.items
    if not valid_items:
        raise HTTPException(status_code=422, detail={"code": "no_valid_faqs", "rows": row_errors})
    if any(item.publish for item in valid_items):
        raise HTTPException(status_code=409, detail="search_evaluation_unavailable")

    prepared = [_faq_candidate(item, request) for item in valid_items]
    await _validate_faq_links(
        request,
        [key for item in valid_items for key in item.link_keys],
    )
    vectors, model_id = await embed_documents(
        request,
        [candidate.embed_text or "" for candidate, _, _ in prepared],
    )

    async def mutation() -> dict[str, object]:
        draft = await ensure_draft(session, principal.name, "Bulk create FAQs")
        ids = [f"faq:{faq_id}" for _, _, faq_id in prepared]
        if len(ids) != len(set(ids)):
            raise HTTPException(status_code=409, detail="faq_already_exists")
        for key in ids:
            if await session.get(Document, key) is not None:
                raise HTTPException(status_code=409, detail="faq_already_exists")
        items: list[dict[str, object]] = []
        for item, (candidate, metadata, faq_id), vector in zip(
            valid_items,
            prepared,
            vectors,
            strict=True,
        ):
            await _check_faq_links(session, draft.id, item.link_keys)
            document = Document(
                doc_key=f"faq:{faq_id}",
                doc_type="faq",
                title=item.question,
                origin="manual",
                aliases=_unique_values(item.variants),
                status="active",
            )
            session.add(document)
            await session.flush()
            chunk = await add_chunk_version(
                session,
                candidate,
                actor=principal.name,
                origin="manual",
                embedding=vector,
                embedding_model=model_id,
            )
            await attach_chunk(session, draft.id, chunk)
            add_audit_record(
                session,
                actor=principal.name,
                action="faq.create",
                target=document.doc_key,
                before=None,
                after={"content_hash": chunk.content_hash, "faq": metadata},
                trace_id=request.state.trace_id,
            )
            items.append({"id": faq_id, "document": _faq_view(document, chunk)})
        return {"items": items, "partial": bool(row_errors), "invalid_rows": row_errors}

    return await execute_idempotently(
        session,
        request,
        principal,
        {
            "items": [item.model_dump(mode="json") for item in valid_items],
            "invalid_rows": row_errors,
        },
        mutation,
    )


@router.patch("/faqs/{faq_id}")
async def update_faq(
    faq_id: str,
    body: FAQPatch,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, object]:
    doc_key = faq_id if faq_id.startswith("faq:") else f"faq:{faq_id}"
    session_factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if session_factory is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    async with session_factory() as read_session:
        release_id = await _current_release_id(read_session)
        pair = (
            await _faq_pair(read_session, release_id, doc_key) if release_id is not None else None
        )
    if pair is None:
        raise HTTPException(status_code=404, detail="faq_not_found")
    _, current_chunk = pair
    merged = _merge_faq(current_chunk, body)
    _reject_inline_publish(False)
    candidate, metadata, _ = _faq_candidate(merged, request, faq_id.removeprefix("faq:"))
    await _validate_faq_links(request, merged.link_keys)
    vectors, model_id = await embed_documents(request, [candidate.embed_text or ""])

    async def mutation() -> dict[str, object]:
        draft = await ensure_draft(session, principal.name, "Update FAQ")
        latest = await _faq_pair(session, draft.id, doc_key)
        if latest is None:
            raise HTTPException(status_code=404, detail="faq_not_found")
        document, old_chunk = latest
        await _check_faq_links(session, draft.id, merged.link_keys)
        document.title = merged.question
        document.aliases = _unique_values(merged.variants)
        chunk = await add_chunk_version(
            session,
            candidate,
            actor=principal.name,
            origin="manual",
            embedding=vectors[0],
            embedding_model=model_id,
            overrides_id=old_chunk.id if old_chunk.origin == "etl" else old_chunk.overrides_id,
            change_note="FAQ update",
            trace_id=request.state.trace_id,
        )
        await attach_chunk(session, draft.id, chunk)
        add_audit_record(
            session,
            actor=principal.name,
            action="faq.update",
            target=doc_key,
            before={"content_hash": old_chunk.content_hash},
            after={"content_hash": chunk.content_hash, "faq": metadata},
            trace_id=request.state.trace_id,
        )
        return _faq_view(document, chunk)

    return await execute_idempotently(
        session,
        request,
        principal,
        body.model_dump(mode="json", exclude_unset=True),
        mutation,
    )


@router.delete("/faqs/{faq_id}")
async def delete_faq(
    faq_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.WRITE))],
) -> dict[str, str]:
    doc_key = faq_id if faq_id.startswith("faq:") else f"faq:{faq_id}"

    async def mutation() -> dict[str, str]:
        document = await session.get(Document, doc_key)
        if document is None:
            raise HTTPException(status_code=404, detail="faq_not_found")
        draft = await ensure_draft(session, principal.name, "Delete FAQ")
        current = (await release_chunks(session, draft.id)).get(f"{doc_key}#qa")
        if current is None:
            raise HTTPException(status_code=404, detail="faq_not_found")
        document.status = "archived"
        await remove_chunk_from_release(session, draft.id, current.chunk_key)
        add_audit_record(
            session,
            actor=principal.name,
            action="faq.delete",
            target=doc_key,
            before={"content_hash": current.content_hash},
            after={"status": "archived"},
            trace_id=request.state.trace_id,
        )
        return {"status": "archived"}

    return await execute_idempotently(
        session,
        request,
        principal,
        {"faq_id": faq_id, "action": "delete"},
        mutation,
    )


async def _parse_bulk(request: Request) -> tuple[FAQBulkRequest, dict[int, str]]:
    settings = request.app.state.settings
    limit = settings.etl_max_json_mb * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > limit:
        raise HTTPException(status_code=413, detail="upload_too_large")
    raw = bytearray()
    async for part in request.stream():
        if len(raw) + len(part) > limit:
            raise HTTPException(status_code=413, detail="upload_too_large")
        raw.extend(part)
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
    try:
        if content_type == "text/csv":
            items, errors = _csv_items(bytes(raw).decode("utf-8-sig"))
            partial = request.query_params.get("partial", "false").lower() == "true"
            return FAQBulkRequest(items=items, partial=partial), errors
        payload = json.loads(raw)
        return FAQBulkRequest.model_validate(payload), {}
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid_faq_bulk_payload") from exc


def _csv_items(text: str) -> tuple[list[FAQCreate], dict[int, str]]:
    reader = csv.DictReader(StringIO(text))
    required = {"question", "answer"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV requires question and answer columns")
    items: list[FAQCreate] = []
    errors: dict[int, str] = {}
    for row_number, row in enumerate(reader, start=2):
        try:
            payload: dict[str, Any] = {
                "question": row.get("question", ""),
                "answer": row.get("answer", ""),
                "variants": _split_csv_list(row.get("variants")),
                "link_keys": _split_csv_list(row.get("link_keys")),
                "tags": _split_csv_list(row.get("tags")),
                "direct": _csv_bool(row.get("direct"), default=True),
                "review_after": row.get("review_after") or None,
                "publish": False,
            }
            items.append(FAQCreate.model_validate(payload))
        except ValidationError:
            errors[row_number] = "invalid_row"
        except ValueError:
            errors[row_number] = "invalid_row"
    return items, errors


def _split_csv_list(value: str | None) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()] if value else []


def _csv_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    lowered = value.strip().lower()
    if lowered not in {"true", "false"}:
        raise ValueError("CSV boolean must be true or false")
    return lowered == "true"


def _faq_candidate(
    body: FAQCreate,
    request: Request,
    faq_id: str | None = None,
) -> tuple[ContentChunk, dict[str, object], str]:
    variants = _unique_values(body.variants)
    link_keys = _unique_values(body.link_keys)
    slug = faq_id or _slug(body.question)
    if not slug:
        raise HTTPException(status_code=422, detail="faq_question_has_no_identifier")
    metadata: dict[str, object] = {
        "faq": {
            "question": body.question,
            "answer": body.answer,
            "variants": variants,
            "link_keys": link_keys,
            "tags": body.tags,
            "direct": body.direct,
            "review_after": body.review_after.isoformat() if body.review_after else None,
            "watch": body.watch,
        },
        "link_keys": link_keys,
    }
    embed_text = "\n".join([body.question, *variants])
    try:
        candidate = build_manual_chunk(
            f"faq:{slug}#qa",
            f"faq:{slug}",
            "faq",
            f"Q: {body.question}\nA: {body.answer}",
            embed_text,
            metadata,
            request.app.state.settings.chunk_hard_max_tokens,
        )
    except ContentValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return candidate, metadata, slug


def _merge_faq(current: Chunk, body: FAQPatch) -> FAQCreate:
    metadata = _faq_metadata(current)
    updates = body.model_dump(mode="json", exclude_unset=True)
    values = {**metadata, **updates, "publish": False}
    try:
        return FAQCreate.model_validate(values)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid_faq") from exc


async def _validate_faq_links(request: Request, link_keys: list[str]) -> None:
    if not link_keys:
        return
    session_factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if session_factory is None:
        raise HTTPException(status_code=503, detail="database_unavailable")
    async with session_factory() as session:
        release_id = await _current_release_id(session)
        if release_id is None:
            raise HTTPException(status_code=422, detail="unknown_faq_link_key")
        await _check_faq_links(session, release_id, link_keys)


async def _check_faq_links(session: AsyncSession, release_id: int, link_keys: list[str]) -> None:
    try:
        await validate_link_keys(session, release_id, link_keys)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unknown_faq_link_key") from exc


async def _current_release_id(session: AsyncSession) -> int | None:
    draft_id = await session.scalar(select(Release.id).where(Release.status == "draft"))
    return draft_id if draft_id is not None else await active_release_id(session)


async def _faq_pairs(
    session: AsyncSession,
    release_id: int,
) -> list[tuple[Document, Chunk]]:
    rows = (
        await session.execute(
            select(Document, Chunk)
            .join(Chunk, Chunk.doc_key == Document.doc_key)
            .join(ReleaseChunk, ReleaseChunk.chunk_id == Chunk.id)
            .where(
                Document.doc_type == "faq",
                Document.status == "active",
                ReleaseChunk.release_id == release_id,
            )
            .order_by(Document.doc_key.asc())
        )
    ).all()
    return [(document, chunk) for document, chunk in rows]


async def _faq_pair(
    session: AsyncSession,
    release_id: int,
    doc_key: str,
) -> tuple[Document, Chunk] | None:
    return next(
        (pair for pair in await _faq_pairs(session, release_id) if pair[0].doc_key == doc_key),
        None,
    )


def _faq_metadata(chunk: Chunk) -> dict[str, Any]:
    value = chunk.metadata_json.get("faq", {})
    return value if isinstance(value, dict) else {}


def _faq_view(document: Document, chunk: Chunk) -> dict[str, object]:
    metadata = _faq_metadata(chunk)
    return {
        "id": document.doc_key.removeprefix("faq:"),
        "doc_key": document.doc_key,
        "question": metadata.get("question", document.title),
        "answer": metadata.get("answer", chunk.text),
        "variants": metadata.get("variants", []),
        "link_keys": metadata.get("link_keys", []),
        "tags": metadata.get("tags", []),
        "direct": metadata.get("direct", True),
        "review_after": metadata.get("review_after"),
        "watch": metadata.get("watch", []),
        "chunk_key": chunk.chunk_key,
        "version": chunk.version,
        "content_hash": chunk.content_hash,
    }


def _is_faq_due(chunk: Chunk, today: date, include_due: bool) -> bool:
    raw_date = _faq_metadata(chunk).get("review_after")
    if not include_due:
        return True
    if not isinstance(raw_date, str):
        return False
    try:
        return date.fromisoformat(raw_date) <= today
    except ValueError:
        return False


def _unique_values(values: list[str]) -> list[str]:
    normalized = [value.strip() for value in values if value.strip()]
    if len(normalized) != len(set(normalized)):
        raise HTTPException(status_code=422, detail="values_must_be_unique")
    return normalized


def _reject_inline_publish(publish: bool) -> None:
    if publish:
        raise HTTPException(status_code=409, detail="search_evaluation_unavailable")


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.casefold())).strip("-")
