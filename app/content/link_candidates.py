from __future__ import annotations

from urllib.parse import SplitResult, parse_qs

from app.content.models import SourceLink


def add_link_candidate(
    links: dict[str, SourceLink],
    url: str,
    parts: SplitResult,
) -> None:
    key, kind, label = _link_details(parts)
    links.setdefault(key, SourceLink(link_key=key, kind=kind, label=label, url=url))
    if parts.path == "/contact":
        links.setdefault(
            "contact:admissions",
            SourceLink(
                link_key="contact:admissions",
                kind="contact",
                label="Contact admissions",
                url=url,
            ),
        )


def _link_details(parts: SplitResult) -> tuple[str, str, str]:
    query = parse_qs(parts.query)
    if parts.path == "/apply":
        return _application_link(query)
    if parts.path.startswith("/courses/"):
        course_name = parts.path.rsplit("/", maxsplit=1)[-1].replace("-", " ")
        return (
            f"course:{parts.path.removeprefix('/courses/')}",
            "course",
            f"Course: {course_name}",
        )
    category = query.get("category", [""])[0]
    if parts.path == "/courses" and category:
        category_name = category.replace("-", " ")
        return f"category:{category}", "category", f"Courses: {category_name}"
    path_slug = parts.path.strip("/").replace("/", ":") or "home"
    return f"page:{path_slug}", "page", path_slug.replace(":", " ").title()


def _application_link(query: dict[str, list[str]]) -> tuple[str, str, str]:
    slug = query.get("course", [""])[0]
    if slug:
        return f"apply:{slug}", "apply", f"Apply: {slug.replace('-', ' ')}"
    if query.get("topic") == ["scholarship"]:
        return "apply:scholarship", "apply", "Apply for scholarship"
    return "apply:general", "apply", "Apply"
