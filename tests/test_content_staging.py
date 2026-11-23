from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.config import Settings
from app.content.models import (
    ContentChunk,
    CrawlImport,
    DryRunReport,
    SourceDocument,
)
from app.content.staging import _stage_run


class _Rows:
    def all(self) -> list[object]:
        return []


class _Session:
    active = False

    async def __aenter__(self) -> _Session:
        self.active = True
        return self

    async def __aexit__(self, *_: object) -> None:
        self.active = False

    async def scalar(self, _statement: object) -> None:
        return None

    async def scalars(self, _statement: object) -> _Rows:
        return _Rows()


class _SessionFactory:
    def __init__(self) -> None:
        self.session = _Session()

    def __call__(self) -> _Session:
        return self.session


class _Embeddings:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def embed_texts(
        self,
        texts: list[str],
        *,
        input_type: str,
    ) -> list[list[float]]:
        assert not self.session.active
        assert input_type == "document"
        return [[0.0] * 768 for _ in texts]


def _crawl() -> CrawlImport:
    chunk = ContentChunk(
        chunk_key="page:about#summary",
        doc_key="page:about",
        kind="fact",
        text="Public site content.",
        token_count=10,
        content_hash="content-hash",
        metadata={},
    )
    report = DryRunReport(
        manifest_candidates=1,
        included_urls=1,
        excluded_urls=0,
        available_markdown_pages=1,
        markdown_files=1,
        direct_pages_loaded=1,
        query_pages_skipped=0,
        course_pages=0,
        generated_chunks=1,
        links=0,
        chunk_kinds={"fact": 1},
        missing_direct_pages=(),
        missing_course_fields={},
        estimated_chunk_tokens={"min": 10, "max": 10},
        estimated_all_chunk_tokens={"min": 10, "max": 10},
        oversized_chunks=0,
        generated_documents=1,
        document_types={"page": 1},
        category_count=0,
        programme_count=0,
        source_conflicts=0,
        source_conflict_details=(),
        unknown_headings=(),
        warnings=(),
    )
    return CrawlImport(
        pages=(),
        documents=(SourceDocument("page:about", "page", "About", "/about", "source-hash"),),
        chunks=(chunk,),
        links=(),
        report=report,
        payload_hash="payload-hash",
        supporting_sources_loaded=True,
    )


async def test_embeddings_are_requested_after_database_session_closes(monkeypatch) -> None:
    import app.content.staging as staging

    session_factory = _SessionFactory()
    session = session_factory.session
    embeddings = _Embeddings(session)
    commit_result = {"status": "succeeded"}

    async def fake_commit(*_args: object, **_kwargs: object) -> dict[str, object]:
        assert not session.active
        return commit_result

    async def no_base_release(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(staging, "_commit_stage", fake_commit)
    monkeypatch.setattr(staging, "_base_release_id", no_base_release)

    result = await _stage_run(
        session_factory,  # type: ignore[arg-type]
        SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        _crawl(),
        embeddings,  # type: ignore[arg-type]
        Settings(_env_file=None),
        actor="owner",
        trace_id=uuid4(),
        force=False,
    )

    assert result == commit_result
