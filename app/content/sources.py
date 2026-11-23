from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.content.course import CourseContent, parse_course
from app.content.models import SourcePage

_FIELD_NAMES = {
    "category": ("category",),
    "duration": ("duration",),
    "tuition": ("price", "tuition"),
    "overview": ("description", "overview"),
    "outcomes": ("outcomes", "curriculum"),
    "skills": ("skills",),
    "careers": ("careers",),
    "entry_requirements": ("entry_requirements", "entryRequirements"),
    "certification": ("certification",),
}


@dataclass(frozen=True, slots=True)
class SourceReconciliation:
    fallback_by_slug: dict[str, dict[str, str]]
    conflicts: tuple[dict[str, str], ...]
    warnings: tuple[str, ...]
    payload_hash: str | None


def reconcile_supporting_sources(
    pages: list[SourcePage],
    courses_path: Path,
    website_content_path: Path,
) -> SourceReconciliation:
    catalog, catalog_hash = _read_course_list(courses_path, "courses.json")
    website_content, website_hash = _read_website_courses(website_content_path)
    parsed_courses = [parse_course(page) for page in pages if page.path.startswith("/courses/")]
    fallback_by_slug: dict[str, dict[str, str]] = {}
    conflicts: list[dict[str, str]] = []
    matched_catalog: set[str] = set()
    matched_website: set[str] = set()

    for course in parsed_courses:
        identity = _identity(course.title)
        catalog_item = catalog.get(identity)
        website_item = website_content.get(identity)
        if catalog_item is not None:
            matched_catalog.add(identity)
        if website_item is not None:
            matched_website.add(identity)
        if catalog_item is None or website_item is None:
            conflicts.append(
                {
                    "code": "supporting_course_missing",
                    "course": course.slug,
                    "source": "courses.json" if catalog_item is None else "website-content.json",
                }
            )
        fallback_by_slug[course.slug] = _reconcile_course_fields(
            course,
            catalog_item,
            website_item,
            conflicts,
        )

    _append_unmatched_conflicts(catalog, matched_catalog, "courses.json", conflicts)
    _append_unmatched_conflicts(
        website_content,
        matched_website,
        "website-content.json",
        conflicts,
    )
    return SourceReconciliation(
        fallback_by_slug=fallback_by_slug,
        conflicts=tuple(conflicts),
        warnings=(),
        payload_hash=hashlib.sha256(f"{catalog_hash}:{website_hash}".encode()).hexdigest(),
    )


def _read_course_list(path: Path, source: str) -> tuple[dict[str, dict[str, Any]], str]:
    records, digest = _read_json(path, source)
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError(f"{source} must contain a list of course objects")
    return _index_courses(records, source), digest


def _read_website_courses(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    payload, digest = _read_json(path, "website-content.json")
    if not isinstance(payload, dict) or not isinstance(payload.get("courses"), list):
        raise ValueError("website-content.json must contain a courses list")
    records = payload["courses"]
    if not all(isinstance(item, dict) for item in records):
        raise ValueError("website-content.json courses must be objects")
    return _index_courses(records, "website-content.json"), digest


def _read_json(path: Path, source: str) -> tuple[object, str]:
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read valid UTF-8 JSON from {source}") from exc


def _index_courses(
    records: list[dict[str, Any]],
    source: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        title = record.get("title")
        identity = _identity(title) if isinstance(title, str) else ""
        if not identity:
            raise ValueError(f"{source} contains a course without a title or slug")
        if identity in indexed:
            raise ValueError(f"{source} contains duplicate course identity")
        indexed[identity] = record
    return indexed


def _reconcile_course_fields(
    course: CourseContent,
    catalog: dict[str, Any] | None,
    website_content: dict[str, Any] | None,
    conflicts: list[dict[str, str]],
) -> dict[str, str]:
    fallback: dict[str, str] = {}
    for field, names in _FIELD_NAMES.items():
        crawl_value = getattr(course, field)
        values = _source_values(field, names, catalog, website_content)
        if crawl_value:
            conflicts.extend(
                {
                    "code": "source_value_conflict",
                    "course": course.slug,
                    "field": field,
                    "source": source,
                }
                for source, value in values
                if _normalize(value) != _normalize(crawl_value)
            )
            continue
        if not values:
            continue
        if len({_normalize(value) for _, value in values}) > 1:
            conflicts.append(
                {
                    "code": "supporting_sources_disagree",
                    "course": course.slug,
                    "field": field,
                }
            )
            continue
        fallback[field] = values[0][1]
    return fallback


def _source_values(
    field: str,
    names: tuple[str, ...],
    catalog: dict[str, Any] | None,
    website_content: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for source_name, record in (
        ("courses.json", catalog),
        ("website-content.json", website_content),
    ):
        if record is None:
            continue
        value = next((record[name] for name in names if name in record), None)
        text = _text_value(value)
        if text:
            result.append((source_name, text))
    return result


def _text_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "; ".join(item.strip() for item in value if item.strip())
    return ""


def _append_unmatched_conflicts(
    source: dict[str, dict[str, Any]],
    matched: set[str],
    source_name: str,
    conflicts: list[dict[str, str]],
) -> None:
    conflicts.extend(
        {
            "code": "supporting_course_unmatched",
            "course": _course_label(source[identity]),
            "source": source_name,
        }
        for identity in sorted(set(source) - matched)
    )


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _identity(value: str) -> str:
    without_conjunctions = re.sub(r"\band\b", " ", value.casefold())
    return re.sub(r"[^a-z0-9]", "", without_conjunctions)


def _course_label(record: dict[str, Any]) -> str:
    title = record.get("title")
    slug = record.get("slug")
    return slug if isinstance(slug, str) and slug else str(title)
