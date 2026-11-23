from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_embedding_client, require_scope
from app.db.models import Release, Trace
from app.db.session import get_db_session
from app.search.hybrid import InMemoryHybridSearch
from app.security.keys import AdminPrincipal, AdminScope

router = APIRouter(prefix="/admin/v1/debug", tags=["debug"])


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    release: str = "live"


class ReplayRequest(BaseModel):
    trace_id: str
    release: str = "draft"


@router.post("/retrieve")
async def retrieve_debug(
    body: RetrieveRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    snapshot = request.app.state.active_snapshot
    if body.release == "draft":
        draft = await session.scalar(select(Release).where(Release.status == "draft"))
        if draft is None:
            raise HTTPException(status_code=404, detail="draft_not_found")
        raise HTTPException(status_code=501, detail="draft_snapshot_not_loaded")
    if snapshot is None:
        raise HTTPException(status_code=409, detail="no_published_release")
    embeddings = get_embedding_client(request)
    vectors = await embeddings.embed_texts([body.question], input_type="query")
    hits, gate = InMemoryHybridSearch(snapshot).retrieve(tuple(vectors[0]), body.question)
    return {
        "release_id": snapshot.release_id,
        "gate": gate,
        "hits": [
            {
                "chunk_key": hit.chunk_key,
                "doc_key": hit.doc_key,
                "score": hit.score,
                "vector_score": hit.vector_score,
                "bm25_score": hit.bm25_score,
            }
            for hit in hits
        ],
    }


@router.post("/replay")
async def replay_debug(
    body: ReplayRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[AdminPrincipal, Depends(require_scope(AdminScope.READ))],
) -> dict[str, object]:
    from uuid import UUID

    try:
        trace_uuid = UUID(body.trace_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_trace_id") from exc
    trace = await session.get(Trace, trace_uuid)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace_not_found")
    question = trace.user_text
    if not question:
        raise HTTPException(status_code=409, detail="trace_has_no_user_text")
    replay = RetrieveRequest(question=question, release=body.release)
    return await retrieve_debug(replay, request, session, principal)
