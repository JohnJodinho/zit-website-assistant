from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourcePage:
    url: str
    path: str
    title: str
    markdown: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class SourceDocument:
    doc_key: str
    doc_type: str
    title: str
    url_path: str | None
    source_hash: str


@dataclass(frozen=True, slots=True)
class ContentChunk:
    chunk_key: str
    doc_key: str
    kind: str
    text: str
    token_count: int
    content_hash: str
    metadata: dict[str, object]
    embed_text: str | None = None


@dataclass(frozen=True, slots=True)
class SourceLink:
    link_key: str
    kind: str
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class DryRunReport:
    manifest_candidates: int
    included_urls: int
    excluded_urls: int
    available_markdown_pages: int
    markdown_files: int
    direct_pages_loaded: int
    query_pages_skipped: int
    course_pages: int
    generated_chunks: int
    links: int
    chunk_kinds: dict[str, int]
    missing_direct_pages: tuple[str, ...]
    missing_course_fields: dict[str, int]
    estimated_chunk_tokens: dict[str, int | None]
    estimated_all_chunk_tokens: dict[str, int | None]
    oversized_chunks: int
    generated_documents: int
    document_types: dict[str, int]
    category_count: int
    programme_count: int
    source_conflicts: int
    source_conflict_details: tuple[dict[str, str], ...]
    unknown_headings: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrawlImport:
    pages: tuple[SourcePage, ...]
    documents: tuple[SourceDocument, ...]
    chunks: tuple[ContentChunk, ...]
    links: tuple[SourceLink, ...]
    report: DryRunReport
    payload_hash: str
    warnings: tuple[str, ...] = ()
    source_conflicts: tuple[dict[str, str], ...] = ()
    supporting_sources_loaded: bool = False
