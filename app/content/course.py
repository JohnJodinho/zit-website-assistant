from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.content.hashing import hash_content
from app.content.models import ContentChunk, SourcePage
from app.content.text import slugify

_COURSE_FIELDS = (
    "category",
    "programme",
    "duration",
    "tuition",
    "overview",
    "outcomes",
    "skills",
    "careers",
    "entry_requirements",
    "certification",
)
_SECTION_NAMES = {
    "about the course": "overview",
    "what you will learn": "outcomes",
    "skills you will build": "skills",
    "career opportunities": "careers",
}


@dataclass(frozen=True, slots=True)
class CourseContent:
    slug: str
    title: str
    category: str
    programme: str
    duration: str
    tuition: str
    overview: str
    outcomes: str
    skills: str
    careers: str
    entry_requirements: str
    certification: str
    source_hash: str
    extra_sections: tuple[tuple[str, str], ...] = ()


def build_course_chunks(
    pages: list[SourcePage],
    fallback_by_slug: Mapping[str, Mapping[str, str]] | None = None,
) -> list[ContentChunk]:
    chunks: list[ContentChunk] = []
    for page in pages:
        fallback = (
            fallback_by_slug.get(page.path.removeprefix("/courses/").strip("/"), {})
            if fallback_by_slug
            else {}
        )
        chunks.extend(_course_chunks(parse_course(page, fallback)))
    return chunks


def course_quality(chunks: list[ContentChunk]) -> tuple[dict[str, int], dict[str, int | None]]:
    course_facts = [chunk.metadata for chunk in chunks if chunk.kind == "course_facts"]
    missing_fields = {
        field: sum(not metadata.get(field) for metadata in course_facts) for field in _COURSE_FIELDS
    }
    token_counts = [chunk.token_count for chunk in chunks]
    return missing_fields, {
        "min": min(token_counts) if token_counts else None,
        "max": max(token_counts) if token_counts else None,
    }


def parse_course(
    page: SourcePage,
    fallback_values: Mapping[str, str] | None = None,
) -> CourseContent:
    sections = _sections(page.markdown)
    title_match = re.search(r"(?m)^#\s+.+?\s*$", page.markdown)
    if title_match is None:
        raise ValueError(f"Course page has no title: {page.path}")
    category, programme, duration = _course_header_values(page.markdown, title_match.end())
    tuition_match = re.search(r"(₦\s*[\d,]+)\s*Tuition", page.markdown, re.IGNORECASE)
    values = fallback_values or {}
    return CourseContent(
        slug=page.path.removeprefix("/courses/").strip("/"),
        title=page.title,
        category=_fallback_value(category, values, "category"),
        programme=programme,
        duration=_fallback_value(duration, values, "duration"),
        tuition=(
            tuition_match.group(1).replace(" ", "") if tuition_match else values.get("tuition", "")
        ),
        overview=_fallback_value(sections.get("overview", ""), values, "overview"),
        outcomes=_fallback_value(sections.get("outcomes", ""), values, "outcomes"),
        skills=_fallback_value(sections.get("skills", ""), values, "skills"),
        careers=_fallback_value(sections.get("careers", ""), values, "careers"),
        entry_requirements=_fallback_value(
            _bold_value(page.markdown, "Entry requirements"),
            values,
            "entry_requirements",
        ),
        certification=_fallback_value(
            _bold_value(page.markdown, "Certification"),
            values,
            "certification",
        ),
        source_hash=_course_source_hash(page.source_hash, values),
        extra_sections=_unknown_sections(page.markdown),
    )


def _course_header_values(markdown: str, title_end: int) -> tuple[str, str, str]:
    intro = markdown[title_end:].split("##", maxsplit=1)[0]
    header_line = next(
        (clean_text(line) for line in intro.splitlines() if "·" in line),
        "",
    )
    parts = [part.strip() for part in header_line.split("·") if part.strip()]
    values = (*parts, "", "", "")
    return values[0], values[1], values[2]


def _fallback_value(primary: str, fallback_values: Mapping[str, str], key: str) -> str:
    return primary or fallback_values.get(key, "")


def clean_text(text: str) -> str:
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)]\((https?://[^)]+|/[^)]*)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = re.sub(
        r"(?<![\w@])(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?:/[^\s)]*)?",
        "",
        text,
    )
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"(?m)^\s*[*+-]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _sections(markdown: str) -> dict[str, str]:
    content = markdown[markdown.find("\n# ") + 1 :] if "\n# " in markdown else markdown
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", content))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = _SECTION_NAMES.get(match.group(1).strip().lower())
        if key is None:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        section = content[match.end() : end]
        section = re.split(
            r"(?m)^\s*(?:₦|[*+-]\s*(?:Entry requirements|Certification)\*\*)",
            section,
            maxsplit=1,
        )[0]
        result[key] = clean_text(section)
    return result


def _bold_value(markdown: str, label: str) -> str:
    match = re.search(
        rf"{re.escape(label)}\*\*\s*([^*\n]+)\*\*",
        markdown,
        re.IGNORECASE,
    )
    return clean_text(match.group(1)) if match else ""


def _course_chunks(course: CourseContent) -> list[ContentChunk]:
    metadata = _course_metadata(course)
    content = (
        ("course_facts", _course_facts_text(course)),
        ("learning_careers", _learning_careers_text(course)),
    )
    chunks = [
        _make_course_chunk(course, kind, text, metadata) for kind, text in content if text.strip()
    ]
    return chunks + _extra_course_chunks(course, metadata)


def _course_metadata(course: CourseContent) -> dict[str, object]:
    return {
        "title": course.title,
        "category": course.category,
        "programme": course.programme,
        "duration": course.duration,
        "tuition": course.tuition,
        "overview": course.overview,
        "outcomes": course.outcomes,
        "skills": course.skills,
        "careers": course.careers,
        "entry_requirements": course.entry_requirements,
        "certification": course.certification,
        "volatile": ["tuition"],
        "entity": _course_entity(course),
        "link_keys": [f"course:{course.slug}", f"apply:{course.slug}"],
        "source_hash": course.source_hash,
    }


def _course_facts_text(course: CourseContent) -> str:
    return _join_nonempty(
        [
            f"[Course] {course.title}",
            f"Category: {course.category}" if course.category else "",
            _join_nonempty(
                [
                    f"Programme: {course.programme}" if course.programme else "",
                    f"Duration: {course.duration}" if course.duration else "",
                    f"Tuition: {course.tuition}" if course.tuition else "",
                ]
            ),
            f"Overview: {course.overview}" if course.overview else "",
            (
                f"Entry requirements: {course.entry_requirements}"
                if course.entry_requirements
                else ""
            ),
            f"Certification: {course.certification}" if course.certification else "",
        ]
    )


def _learning_careers_text(course: CourseContent) -> str:
    return _join_nonempty(
        [
            f"[Course] {course.title}",
            f"What you will learn: {course.outcomes}" if course.outcomes else "",
            f"Skills you will build: {course.skills}" if course.skills else "",
            f"Career opportunities: {course.careers}" if course.careers else "",
        ]
    )


def _extra_course_chunks(
    course: CourseContent,
    metadata: dict[str, object],
) -> list[ContentChunk]:
    seen_headings: dict[str, int] = {}
    chunks: list[ContentChunk] = []
    for heading, body in course.extra_sections:
        heading_slug = slugify(heading)
        seen_headings[heading_slug] = seen_headings.get(heading_slug, 0) + 1
        occurrence = seen_headings[heading_slug]
        prefix = f"[Course] {course.title} | {heading}. "
        parts = _split_extra(prefix, body)
        for part_index, text in enumerate(parts, start=1):
            extra_metadata = {
                **metadata,
                "extra_heading": heading,
                "part": part_index,
            }
            chunks.append(
                _make_course_chunk(
                    course,
                    "course_extra",
                    text,
                    extra_metadata,
                    key_suffix=(
                        f"extra-{heading_slug}-{occurrence}-{part_index}"
                        if len(parts) > 1 or occurrence > 1
                        else f"extra-{heading_slug}"
                    ),
                )
            )
    return chunks


def _make_course_chunk(
    course: CourseContent,
    kind: str,
    text: str,
    metadata: dict[str, object],
    *,
    key_suffix: str | None = None,
) -> ContentChunk:
    clean = _without_raw_urls(text)
    return ContentChunk(
        chunk_key=f"course:{course.slug}#{key_suffix or kind}",
        doc_key=f"course:{course.slug}",
        kind=kind,
        text=clean,
        token_count=math.ceil(len(clean) / 3.5),
        content_hash=hash_content(clean, None, metadata),
        metadata=metadata,
    )


def _without_raw_urls(text: str) -> str:
    if re.search(r"https?://|(?:^|\s)/[A-Za-z0-9][^\s]*", text):
        raise ValueError("Generated chunk contains a raw URL")
    return text


def _join_nonempty(values: list[str]) -> str:
    return " ".join(value for value in values if value)


def _course_entity(course: CourseContent) -> dict[str, object]:
    words = course.title.split()
    without_credential = re.sub(
        r"^(?:professional|diploma|certificate|certification)\s+(?:in\s+)?",
        "",
        course.title,
        flags=re.IGNORECASE,
    )
    names = [course.title, without_credential, course.slug.replace("-", " ")]
    initials = "".join(word[0] for word in words if word)
    if len(initials) > 1:
        names.append(initials)
    return {
        "key": f"course:{course.slug}",
        "type": "course",
        "names": list(dict.fromkeys(name for name in names if name)),
    }


def _course_source_hash(source_hash: str, fallback_values: Mapping[str, str]) -> str:
    if not fallback_values:
        return source_hash
    payload = "|".join(f"{key}={fallback_values[key]}" for key in sorted(fallback_values))
    return hashlib.sha256(f"{source_hash}:{payload}".encode()).hexdigest()


def _unknown_sections(markdown: str) -> tuple[tuple[str, str], ...]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown))
    sections: list[tuple[str, str]] = []
    known = set(_SECTION_NAMES)
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        if heading.casefold() in known:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = clean_text(markdown[match.end() : end])
        if body:
            sections.append((heading, body))
    return tuple(sections)


def _split_extra(prefix: str, body: str) -> list[str]:
    words = body.split()
    parts: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join((*current, word))
        if current and math.ceil(len(prefix + candidate) / 3.5) > 350:
            parts.append(prefix + " ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        parts.append(prefix + " ".join(current))
    return parts
