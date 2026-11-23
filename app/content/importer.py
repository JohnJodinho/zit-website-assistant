from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from urllib.parse import SplitResult, parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from app.content.course import build_course_chunks, clean_text, course_quality
from app.content.link_candidates import add_link_candidate
from app.content.models import (
    ContentChunk,
    CrawlImport,
    DryRunReport,
    SourceDocument,
    SourceLink,
    SourcePage,
)
from app.content.site import build_site_content
from app.content.sources import SourceReconciliation, reconcile_supporting_sources
from app.content.text import slugify

_SITE_HOST = "www.zibeh.ng"
_EXPECTED_COURSES = 45
_APPROVED_CRAWL_ID = "7edb010b-46ff-5707-a3ae-7c8c8c93ae3e"


class ManifestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    page_id: int | None
    decision: Literal["included", "excluded"]
    reason: str
    matched_rule: str | None
    content_status: Literal["available", "unavailable"]


class CrawlManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_candidates: int
    included: int
    excluded: int
    outside_scope: int
    unavailable_content: int
    grammar_version: str
    items: list[ManifestItem]


class CrawlMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crawl_id: str = Field(min_length=1)
    format: Literal["markdown"]
    include_assets: bool


def load_crawl_import(
    export_dir: Path,
    *,
    expected_courses: int = _EXPECTED_COURSES,
    courses_json: Path | None = None,
    website_content_json: Path | None = None,
) -> CrawlImport:
    root = export_dir.resolve(strict=True)
    manifest = _load_manifest(root)
    markdown_count = _validate_markdown_files(root, manifest)
    pages, links, query_pages, missing_pages, payload_hash = _read_manifest_pages(root, manifest)
    _validate_loaded_pages(missing_pages, pages, expected_courses)
    course_pages = [page for page in pages if page.path.startswith("/courses/")]
    reconciliation = _load_reconciliation(
        pages,
        courses_json,
        website_content_json,
    )
    documents, chunks, category_count, programme_count = build_site_content(
        pages,
        reconciliation.fallback_by_slug,
    )
    links = _canonicalize_category_links(links, documents)
    _validate_unique_chunk_keys(chunks)
    course_chunks = build_course_chunks(course_pages, reconciliation.fallback_by_slug)
    report, warnings = _build_report(
        manifest=manifest,
        markdown_count=markdown_count,
        pages=pages,
        links=links,
        query_pages=query_pages,
        missing_pages=missing_pages,
        course_pages=course_pages,
        course_chunks=course_chunks,
        documents=documents,
        chunks=chunks,
        category_count=category_count,
        programme_count=programme_count,
        reconciliation=reconciliation,
    )
    payload_hash = _complete_payload_hash(
        root,
        payload_hash,
        reconciliation,
        documents,
        chunks,
        links.values(),
    )
    return CrawlImport(
        pages=tuple(pages),
        documents=tuple(documents),
        chunks=tuple(chunks),
        links=tuple(links.values()),
        report=report,
        payload_hash=payload_hash,
        warnings=warnings,
        source_conflicts=reconciliation.conflicts,
        supporting_sources_loaded=reconciliation.payload_hash is not None,
    )


def _validate_markdown_files(root: Path, manifest: CrawlManifest) -> int:
    markdown_files = tuple((root / "https_").rglob("*.md"))
    if any(path.is_symlink() for path in markdown_files):
        raise ValueError("Crawl export must not contain symbolic links")
    expected = _expected_markdown_paths(root, manifest)
    actual = {path.resolve() for path in markdown_files}
    if len(actual - expected) != _query_url_count(manifest):
        raise ValueError("Crawl export contains unlisted Markdown files")
    return len(markdown_files)


def _expected_markdown_paths(root: Path, manifest: CrawlManifest) -> set[Path]:
    return {
        _page_path(root, urlsplit(str(item.url)).path).resolve()
        for item in manifest.items
        if item.decision == "included"
        and item.content_status == "available"
        and not urlsplit(str(item.url)).query
    }


def _query_url_count(manifest: CrawlManifest) -> int:
    return sum(
        item.decision == "included" and bool(urlsplit(str(item.url)).query)
        for item in manifest.items
    )


def _validate_loaded_pages(
    missing_pages: list[str],
    pages: list[SourcePage],
    expected_courses: int,
) -> None:
    if missing_pages:
        raise ValueError(f"{len(missing_pages)} included direct pages are missing from the export")
    course_count = sum(page.path.startswith("/courses/") for page in pages)
    if course_count != expected_courses:
        raise ValueError(f"Expected {expected_courses} course pages, found {course_count}")


def _load_reconciliation(
    pages: list[SourcePage],
    courses_json: Path | None,
    website_content_json: Path | None,
) -> SourceReconciliation:
    if (courses_json is None) != (website_content_json is None):
        raise ValueError("Both approved supporting JSON sources must be provided together")
    if courses_json is None or website_content_json is None:
        return _missing_supporting_sources()
    return reconcile_supporting_sources(pages, courses_json, website_content_json)


def _build_report(
    *,
    manifest: CrawlManifest,
    markdown_count: int,
    pages: list[SourcePage],
    links: dict[str, SourceLink],
    query_pages: int,
    missing_pages: list[str],
    course_pages: list[SourcePage],
    course_chunks: list[ContentChunk],
    documents: Sequence[SourceDocument],
    chunks: Sequence[ContentChunk],
    category_count: int,
    programme_count: int,
    reconciliation: SourceReconciliation,
) -> tuple[DryRunReport, tuple[str, ...]]:
    missing_course_fields, _ = course_quality(course_chunks)
    unknown_headings = _unknown_headings(course_chunks)
    warnings = _report_warnings(missing_course_fields, unknown_headings, reconciliation)
    report = DryRunReport(
        manifest_candidates=manifest.total_candidates,
        included_urls=manifest.included,
        excluded_urls=manifest.excluded,
        available_markdown_pages=sum(
            item.decision == "included" and item.content_status == "available"
            for item in manifest.items
        ),
        markdown_files=markdown_count,
        direct_pages_loaded=len(pages),
        query_pages_skipped=query_pages,
        course_pages=len(course_pages),
        generated_chunks=len(chunks),
        links=len(links),
        chunk_kinds=dict(Counter(chunk.kind for chunk in chunks)),
        missing_direct_pages=tuple(missing_pages),
        missing_course_fields=missing_course_fields,
        estimated_chunk_tokens=_token_range(course_chunks),
        estimated_all_chunk_tokens=_token_range(chunks),
        oversized_chunks=sum(chunk.token_count > 350 for chunk in chunks),
        generated_documents=len(documents),
        document_types=dict(Counter(document.doc_type for document in documents)),
        category_count=category_count,
        programme_count=programme_count,
        source_conflicts=len(reconciliation.conflicts),
        source_conflict_details=reconciliation.conflicts,
        unknown_headings=unknown_headings,
        warnings=warnings,
    )
    return report, warnings


def _unknown_headings(course_chunks: Sequence[ContentChunk]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                heading
                for chunk in course_chunks
                if isinstance((heading := chunk.metadata.get("extra_heading")), str)
            }
        )
    )


def _report_warnings(
    missing_course_fields: dict[str, int],
    unknown_headings: tuple[str, ...],
    reconciliation: SourceReconciliation,
) -> tuple[str, ...]:
    missing = tuple(
        f"Course field missing: {field} ({count})"
        for field, count in missing_course_fields.items()
        if count
    )
    unknown = tuple(f"Unknown course heading preserved: {heading}" for heading in unknown_headings)
    return missing + reconciliation.warnings + unknown


def _token_range(chunks: Sequence[ContentChunk]) -> dict[str, int | None]:
    token_counts = [chunk.token_count for chunk in chunks]
    return {
        "min": min(token_counts) if token_counts else None,
        "max": max(token_counts) if token_counts else None,
    }


def _complete_payload_hash(
    root: Path,
    content_hash: str,
    reconciliation: SourceReconciliation,
    documents: Sequence[SourceDocument],
    chunks: Sequence[ContentChunk],
    links: Iterable[SourceLink],
) -> str:
    metadata_hash = hashlib.sha256((root / "metadata.json").read_bytes()).hexdigest()
    payload = {
        "source_hash": content_hash,
        "metadata_hash": metadata_hash,
        "supporting_hash": reconciliation.payload_hash,
        "documents": sorted(
            (item.doc_key, item.doc_type, item.title, item.url_path or "", item.source_hash)
            for item in documents
        ),
        "chunks": sorted((item.chunk_key, item.content_hash) for item in chunks),
        "links": sorted((item.link_key, item.kind, item.label, item.url) for item in links),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_unique_chunk_keys(chunks: Sequence[ContentChunk]) -> None:
    counts = Counter(chunk.chunk_key for chunk in chunks)
    duplicates = [key for key, count in counts.items() if count > 1]
    if duplicates:
        raise ValueError(f"Generated content contains {len(duplicates)} duplicate chunk keys")


def _canonicalize_category_links(
    links: dict[str, SourceLink],
    documents: Sequence[SourceDocument],
) -> dict[str, SourceLink]:
    categories: dict[str, list[str]] = {}
    for document in documents:
        if document.doc_type != "category" or document.doc_key == "category:all":
            continue
        slug = document.doc_key.removeprefix("category:")
        categories.setdefault(_category_normal_form(slug), []).append(document.doc_key)

    canonical_links: dict[str, SourceLink] = {}
    for link in links.values():
        key = link.link_key
        if link.kind == "category":
            value = parse_qs(urlsplit(link.url).query).get("category", [""])[0]
            candidates = categories.get(_category_normal_form(value), [])
            if len(candidates) == 1:
                key = candidates[0]
        canonical_links.setdefault(
            key,
            SourceLink(
                link_key=key,
                kind=link.kind,
                label=link.label,
                url=link.url,
            ),
        )
    return canonical_links


def _category_normal_form(value: str) -> str:
    return slugify(value.replace("&", " and ")).replace("-and-", "-")


def _read_manifest_pages(
    root: Path, manifest: CrawlManifest
) -> tuple[list[SourcePage], dict[str, SourceLink], int, list[str], str]:
    pages: list[SourcePage] = []
    links: dict[str, SourceLink] = {}
    missing_pages: list[str] = []
    query_pages = 0
    items_hash = hashlib.sha256()

    for item in manifest.items:
        items_hash.update(item.model_dump_json().encode("utf-8"))
        page, query_skipped, missing_url = _read_source_page(root, item, links)
        query_pages += int(query_skipped)
        if missing_url is not None:
            missing_pages.append(missing_url)
        if page is not None:
            pages.append(page)
            items_hash.update(page.source_hash.encode("ascii"))
    return pages, links, query_pages, missing_pages, items_hash.hexdigest()


def _read_source_page(
    root: Path, item: ManifestItem, links: dict[str, SourceLink]
) -> tuple[SourcePage | None, bool, str | None]:
    url = str(item.url)
    parts = urlsplit(url)
    if not _is_approved_url(parts):
        raise ValueError("Crawl manifest contains a URL outside the approved site")
    if item.decision != "included":
        return None, False, None

    add_link_candidate(links, url, parts)
    if item.content_status != "available" or parts.query:
        return None, bool(parts.query), None

    page_path = _page_path(root, parts.path)
    if not page_path.is_file():
        return None, False, url
    if page_path.is_symlink() or not page_path.resolve().is_relative_to(root):
        raise ValueError("Crawl page path escapes the approved export")

    markdown = page_path.read_text(encoding="utf-8")
    page_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return (
        SourcePage(
            url=url,
            path=parts.path or "/",
            title=_page_title(markdown, parts.path),
            markdown=markdown,
            source_hash=page_hash,
        ),
        False,
        None,
    )


def _is_approved_url(parts: SplitResult) -> bool:
    return (
        parts.hostname == _SITE_HOST
        and parts.scheme == "https"
        and parts.username is None
        and parts.password is None
        and not parts.fragment
        and not any(segment in {".", ".."} for segment in parts.path.split("/"))
    )


def inspect_supporting_json(courses_path: Path, website_content_path: Path) -> dict[str, int]:
    courses = _load_json(courses_path)
    content = _load_json(website_content_path)
    if not isinstance(courses, list) or not all(isinstance(item, dict) for item in courses):
        raise ValueError("courses.json must contain a list of course objects")
    if not isinstance(content, dict):
        raise ValueError("website-content.json must contain an object")
    course_items = content.get("courses")
    if not isinstance(course_items, list):
        raise ValueError("website-content.json must contain a courses list")
    return {
        "course_catalog_items": len(courses),
        "website_courses": len(course_items),
        "albums": _list_count(content, "albums"),
        "events": _list_count(content, "events"),
        "cohorts": _list_count(content, "cohorts"),
    }


def report_as_dict(report: DryRunReport) -> dict[str, object]:
    return asdict(report)


def _load_manifest(root: Path) -> CrawlManifest:
    manifest_path = root / "manifest.json"
    metadata_path = root / "metadata.json"
    if not manifest_path.is_file() or not metadata_path.is_file():
        raise ValueError("Crawl export must include manifest.json and metadata.json")
    try:
        metadata = CrawlMetadata.model_validate(_load_json(metadata_path))
    except ValidationError as exc:
        raise ValueError("Crawl metadata has an invalid structure") from exc
    if metadata.crawl_id != _APPROVED_CRAWL_ID or metadata.include_assets:
        raise ValueError("Crawl metadata does not match the approved export")
    try:
        manifest = CrawlManifest.model_validate(_load_json(manifest_path))
    except ValidationError as exc:
        raise ValueError("Crawl manifest has an invalid structure") from exc
    _validate_manifest_counts(manifest)
    return manifest


def _validate_manifest_counts(manifest: CrawlManifest) -> None:
    if manifest.grammar_version != "1":
        raise ValueError("Manifest grammar_version is not supported")
    _validate_manifest_decisions(manifest)
    _validate_manifest_item_counts(manifest)


def _validate_manifest_decisions(manifest: CrawlManifest) -> None:
    if manifest.total_candidates != manifest.included + manifest.excluded + manifest.outside_scope:
        raise ValueError("Manifest total_candidates does not match its decision counts")
    urls = [str(item.url).casefold() for item in manifest.items]
    if len(urls) != len(set(urls)):
        raise ValueError("Manifest contains duplicate URLs")
    page_ids = [item.page_id for item in manifest.items if item.page_id is not None]
    if len(page_ids) != len(set(page_ids)):
        raise ValueError("Manifest contains duplicate page IDs")


def _validate_manifest_item_counts(manifest: CrawlManifest) -> None:
    counts = {
        "total_candidates": (len(manifest.items), manifest.total_candidates),
        "included": (
            sum(item.decision == "included" for item in manifest.items),
            manifest.included,
        ),
        "excluded": (
            sum(item.decision == "excluded" for item in manifest.items),
            manifest.excluded,
        ),
        "unavailable_content": (
            sum(item.content_status == "unavailable" for item in manifest.items),
            manifest.unavailable_content,
        ),
    }
    for name, (actual, expected) in counts.items():
        if actual != expected:
            raise ValueError(f"Manifest {name} does not match its items")


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read valid UTF-8 JSON from {path.name}") from exc


def _page_path(root: Path, url_path: str) -> Path:
    path = url_path.strip("/")
    if not path:
        return root / "https_" / f"{_SITE_HOST}.md"
    if any(segment in {".", ".."} for segment in path.split("/")):
        raise ValueError("Crawl URL contains an invalid path")
    relative = Path(*path.split("/")).with_suffix(".md")
    return root / "https_" / _SITE_HOST / relative


def _page_title(markdown: str, url_path: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", markdown)
    if match:
        return clean_text(match.group(1))
    return url_path.strip("/").replace("-", " ").title() or "Home"


def _list_count(payload: dict[str, object], key: str) -> int:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"website-content.json field {key} must be a list")
    return len(value)


def _missing_supporting_sources() -> SourceReconciliation:
    return SourceReconciliation(
        fallback_by_slug={},
        conflicts=(),
        warnings=("Approved supporting course JSON files were not provided.",),
        payload_hash=None,
    )
