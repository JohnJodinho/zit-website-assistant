from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence

from app.content.course import CourseContent, build_course_chunks, clean_text, parse_course
from app.content.hashing import hash_content
from app.content.models import ContentChunk, SourceDocument, SourcePage
from app.content.text import slugify

_PAGE_TYPES = {
    "/": "page",
    "/about": "page",
    "/apply": "page",
    "/contact": "contact",
    "/facilities": "page",
    "/icss": "programme",
    "/programmes": "programme",
    "/se4g": "programme",
    "/services": "service",
}
_FOOTER_HEADINGS = {"study with us", "portals", "the school", "student services", "connect with us"}
_COURSE_COUNT = "course_count"
_CATEGORY_COUNT = "category_count"
_PROGRAMME_COUNT = "programme_count"


def build_site_content(
    pages: list[SourcePage],
    fallback_by_slug: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[list[SourceDocument], list[ContentChunk], int, int]:
    course_pages = [page for page in pages if page.path.startswith("/courses/")]
    course_data = [
        parse_course(
            page,
            fallback_by_slug.get(page.path.removeprefix("/courses/").strip("/"), {})
            if fallback_by_slug
            else None,
        )
        for page in course_pages
    ]
    documents = [
        SourceDocument(
            doc_key=f"course:{course.slug}",
            doc_type="course",
            title=course.title,
            url_path=page.path,
            source_hash=course.source_hash,
        )
        for page, course in zip(course_pages, course_data, strict=True)
    ]
    chunks = build_course_chunks(course_pages, fallback_by_slug)
    categories = _category_content(course_data)
    documents.extend(categories[0])
    chunks.extend(categories[1])

    programme_titles = _programme_titles(pages)
    page_documents, page_chunks = _page_content(pages)
    documents.extend(page_documents)
    chunks.extend(page_chunks)
    count_document, count_chunk = _site_counts_chunk(course_data, categories[2], programme_titles)
    documents.append(count_document)
    chunks.append(count_chunk)
    return documents, chunks, categories[2], len(programme_titles)


def _category_content(
    courses: Sequence[CourseContent],
) -> tuple[list[SourceDocument], list[ContentChunk], int]:
    categories: dict[str, list[str]] = {}
    for course in courses:
        categories.setdefault(course.category, []).append(course.title)

    documents: list[SourceDocument] = []
    chunks: list[ContentChunk] = []
    for category, titles in sorted(categories.items()):
        slug = slugify(category)
        doc_key = f"category:{slug}"
        text = f"[Category] {category} | Courses: {', '.join(sorted(titles))}"
        documents.append(
            SourceDocument(
                doc_key=doc_key,
                doc_type="category",
                title=category,
                url_path="/courses",
                source_hash=_hash(text),
            )
        )
        chunks.append(
            _make_chunk(
                f"{doc_key}#summary",
                doc_key,
                "summary",
                text,
                {
                    "entity": {
                        "key": doc_key,
                        "type": "category",
                        "names": [category, slug.replace("-", " ")],
                    },
                    "link_keys": [doc_key],
                    "source_hash": _hash(text),
                },
            )
        )

    all_titles = sorted(course.title for course in courses)
    all_key = "category:all"
    all_source_hash = _hash(", ".join(all_titles))
    documents.append(
        SourceDocument(
            doc_key=all_key,
            doc_type="category",
            title="All courses",
            url_path="/courses",
            source_hash=all_source_hash,
        )
    )
    chunks.extend(_all_course_chunks(all_key, all_titles))
    return documents, chunks, len(categories)


def _page_content(
    pages: list[SourcePage],
) -> tuple[list[SourceDocument], list[ContentChunk]]:
    documents: list[SourceDocument] = []
    chunks: list[ContentChunk] = []
    for page in pages:
        if page.path not in _PAGE_TYPES:
            continue
        doc_key = f"page:{page.path.strip('/')}" if page.path != "/" else "page:home"
        if page.path == "/contact":
            doc_key = "page:contact"
        link_key = "apply:general" if page.path == "/apply" else doc_key
        sections = _home_partner_sections(page) if page.path == "/" else _page_sections(page)
        if not sections:
            continue
        documents.append(
            SourceDocument(
                doc_key=doc_key,
                doc_type=_PAGE_TYPES[page.path],
                title=page.title,
                url_path=page.path,
                source_hash=page.source_hash,
            )
        )
        heading_occurrences: Counter[str] = Counter()
        chunk_keys: set[str] = set()
        for index, (heading, body) in enumerate(sections):
            safe_heading = slugify(heading)
            heading_occurrences[safe_heading] += 1
            occurrence = heading_occurrences[safe_heading]
            section_chunks = _split_section(page.title, heading, body)
            for part_index, text in enumerate(section_chunks):
                suffix = safe_heading if occurrence == 1 else f"{safe_heading}-{occurrence}"
                if len(section_chunks) > 1:
                    suffix = f"{suffix}-{part_index + 1}"
                chunk_key = f"{doc_key}#{suffix}"
                while chunk_key in chunk_keys:
                    suffix = f"{suffix}-{index + 1}"
                    chunk_key = f"{doc_key}#{suffix}"
                chunk_keys.add(chunk_key)
                chunks.append(
                    _make_chunk(
                        chunk_key,
                        doc_key,
                        "section",
                        text,
                        {
                            "section": heading,
                            "source_hash": page.source_hash,
                            "link_keys": [link_key],
                            "section_order": index,
                            "entity": _page_entity(doc_key, page, heading),
                        },
                    )
                )
    return documents, chunks


def _page_sections(page: SourcePage) -> list[tuple[str, str]]:
    lines = page.markdown.splitlines()
    current_heading: str | None = None
    current_lines: list[str] = []
    sections: list[tuple[str, str]] = []

    def save_section() -> None:
        if current_heading is None:
            return
        body = clean_text("\n".join(current_lines))
        if body:
            sections.append((current_heading, body))

    for line in lines:
        heading = re.match(r"^(#{2,4})\s+(.+?)\s*$", line)
        if heading is None:
            current_lines.append(line)
            continue
        level, title = len(heading.group(1)), clean_text(heading.group(2)).lower()
        if title in _FOOTER_HEADINGS:
            save_section()
            break
        if level > 3:
            current_lines.append(line)
            continue
        save_section()
        current_heading = clean_text(heading.group(2))
        current_lines = []
    save_section()
    if sections:
        return sections

    body = clean_text("\n".join(lines[1:]))
    return [(page.title, body)] if body else []


def _home_partner_sections(page: SourcePage) -> list[tuple[str, str]]:
    return [
        (heading, body)
        for heading, body in _page_sections(page)
        if heading.casefold() == "our partners and ecosystem"
    ]


def _programme_titles(pages: list[SourcePage]) -> list[str]:
    page = next((item for item in pages if item.path == "/programmes"), None)
    if page is None:
        return []
    return [
        clean_text(match.group(1))
        for match in re.finditer(r"(?m)^###\s+(.+?)\s*$", page.markdown)
        if clean_text(match.group(1)).lower() not in _FOOTER_HEADINGS
    ]


def _site_counts_chunk(
    courses: Sequence[CourseContent],
    category_count: int,
    programme_titles: list[str],
) -> tuple[SourceDocument, ContentChunk]:
    by_category = Counter(course.category for course in courses)
    details = ", ".join(f"{name}: {count}" for name, count in sorted(by_category.items()))
    text = (
        f"[Site counts] Courses: {len(courses)}. Categories: {category_count}. "
        f"Programmes: {len(programme_titles)}. Courses by category: {details}."
    )
    doc_key = "fact:site_counts"
    source_hash = _hash(text)
    document = SourceDocument(
        doc_key=doc_key,
        doc_type="fact",
        title="Site counts",
        url_path=None,
        source_hash=source_hash,
    )
    chunk = _make_chunk(
        f"{doc_key}#summary",
        doc_key,
        "fact",
        text,
        {
            _COURSE_COUNT: len(courses),
            _CATEGORY_COUNT: category_count,
            _PROGRAMME_COUNT: len(programme_titles),
            "courses_by_category": dict(sorted(by_category.items())),
            "programme_titles": programme_titles,
            "volatile": [_COURSE_COUNT, _CATEGORY_COUNT, _PROGRAMME_COUNT],
            "source_hash": source_hash,
        },
    )
    return document, chunk


def _all_course_chunks(doc_key: str, titles: list[str]) -> list[ContentChunk]:
    prefix = "[Category] All courses | Courses: "
    groups: list[list[str]] = []
    current: list[str] = []
    for title in titles:
        candidate = [*current, title]
        if current and _token_count(prefix + ", ".join(candidate)) > 350:
            groups.append(current)
            current = [title]
        else:
            current = candidate
    if current:
        groups.append(current)

    return [
        _make_chunk(
            f"{doc_key}#summary-{index + 1}",
            doc_key,
            "summary",
            f"{prefix}{', '.join(group)}",
            {
                "entity": {"key": doc_key, "type": "category", "names": ["all courses", "courses"]},
                "link_keys": ["page:courses"],
                "part": index + 1,
                "parts": len(groups),
                "source_hash": _hash(", ".join(group)),
            },
        )
        for index, group in enumerate(groups)
    ]


def _split_section(page_title: str, heading: str, body: str) -> list[str]:
    prefix = f"[{page_title}] {heading}. "
    words = body.split()
    parts: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and _token_count(prefix + candidate) > 350:
            parts.append(prefix + " ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        parts.append(prefix + " ".join(current))
    return parts


def _make_chunk(
    chunk_key: str,
    doc_key: str,
    kind: str,
    text: str,
    metadata: dict[str, object],
) -> ContentChunk:
    if "https://" in text or "http://" in text:
        raise ValueError(f"Generated chunk contains a raw URL: {chunk_key}")
    return ContentChunk(
        chunk_key=chunk_key,
        doc_key=doc_key,
        kind=kind,
        text=text,
        token_count=_token_count(text),
        content_hash=hash_content(text, None, metadata),
        metadata=metadata,
    )


def _token_count(text: str) -> int:
    return math.ceil(len(text) / 3.5)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _page_entity(doc_key: str, page: SourcePage, heading: str) -> dict[str, object]:
    doc_type = _PAGE_TYPES[page.path]
    if doc_type not in {"programme", "service"}:
        return {"key": doc_key, "type": doc_type, "names": [page.title, heading]}
    return {
        "key": f"{doc_type}:{slugify(heading)}",
        "type": doc_type,
        "names": [heading, page.title],
    }
