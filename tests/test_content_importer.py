from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.content.course import build_course_chunks, parse_course
from app.content.importer import (
    _canonicalize_category_links,
    inspect_supporting_json,
    load_crawl_import,
)
from app.content.models import SourceDocument, SourceLink, SourcePage
from app.content.site import build_site_content


def _write_bundle(root: Path, markdown: str) -> Path:
    export = root / "export"
    page = export / "https_" / "www.zibeh.ng" / "courses" / "diploma-in-cybersecurity.md"
    page.parent.mkdir(parents=True)
    page.write_text(markdown, encoding="utf-8")
    (export / "manifest.json").write_text(
        json.dumps(
            {
                "total_candidates": 1,
                "included": 1,
                "excluded": 0,
                "outside_scope": 0,
                "unavailable_content": 0,
                "grammar_version": "1",
                "items": [
                    {
                        "url": "https://www.zibeh.ng/courses/diploma-in-cybersecurity",
                        "page_id": 1,
                        "decision": "included",
                        "reason": "test",
                        "matched_rule": None,
                        "content_status": "available",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (export / "metadata.json").write_text(
        json.dumps(
            {
                "crawl_id": "7edb010b-46ff-5707-a3ae-7c8c8c93ae3e",
                "format": "markdown",
                "include_assets": False,
            }
        ),
        encoding="utf-8",
    )
    return export


def test_dry_run_parses_course_chunks_and_separates_links(tmp_path: Path) -> None:
    export = _write_bundle(
        tmp_path,
        """# Diploma in Cybersecurity

Cybersecurity · Diploma · 6 Months

## About the course

Learn practical network defence, security operations, incident handling, risk management and safe
systems administration through guided labs, hands-on projects and tutor support. The course
covers current tools, teaches clear reporting, and helps learners prepare for entry-level
cybersecurity roles across different industries.

## What you will learn

* Apply network security controls and identify common threats in business systems
* Assess operational risks and document clear, practical mitigation plans
* Respond to incidents using safe investigation and reporting procedures

## Skills you will build

* Configure network defence tools and review security alerts accurately
* Communicate technical findings to colleagues and supervisors

## Career opportunities

* Cybersecurity analyst supporting security operations and incident response
* Junior network security officer in public or private organizations

₦150,000Tuition
Entry requirements**O'Level with IT background**
Certification**Diploma in Cybersecurity**
""",
    )

    result = load_crawl_import(export, expected_courses=1)

    assert result.report.manifest_candidates == 1
    assert result.report.course_pages == 1
    assert result.report.generated_chunks == 5
    assert all(value == 0 for value in result.report.missing_course_fields.values())
    assert result.report.estimated_chunk_tokens["min"] >= 80
    assert result.report.estimated_chunk_tokens["max"] <= 250
    course_chunks = [chunk for chunk in result.chunks if chunk.doc_key.startswith("course:")]
    assert {chunk.kind for chunk in course_chunks} == {
        "course_facts",
        "learning_careers",
    }
    facts = next(chunk for chunk in course_chunks if chunk.kind == "course_facts")
    learning = next(chunk for chunk in course_chunks if chunk.kind == "learning_careers")
    assert "Cybersecurity" in facts.text
    assert "6 Months" in facts.text
    assert "₦150,000" in facts.text
    assert "network defence" in learning.text.lower()
    assert "Tuition" not in learning.text
    assert "Entry requirements" not in learning.text
    assert all(80 <= chunk.token_count <= 250 for chunk in course_chunks)
    assert all("https://" not in chunk.text for chunk in result.chunks)
    assert any(link.link_key == "course:diploma-in-cybersecurity" for link in result.links)
    assert result.report.missing_direct_pages == ()


def test_course_header_uses_structured_line_not_repeated_accessible_text() -> None:
    course = parse_course(
        SourcePage(
            url="https://www.zibeh.ng/courses/computer-operation",
            path="/courses/computer-operation",
            title="Certification In Computer Operation",
            markdown="""# Certification In Computer Operation

Technology · Certificate · 3 Months

TechnologyCertificate3 Months

## About the course

Introductory course content.
""",
            source_hash="source-hash",
        )
    )

    assert course.category == "Technology"
    assert course.programme == "Certificate"
    assert course.duration == "3 Months"


def test_unknown_course_heading_is_preserved_in_an_extra_chunk() -> None:
    page = SourcePage(
        url="https://www.zibeh.ng/courses/networking",
        path="/courses/networking",
        title="Networking",
        markdown="""# Networking

Technology · Diploma · 3 Months

## Extra admission notes

Applicants should bring a valid identification document to the first session.
""",
        source_hash="source-hash",
    )

    extra = next(chunk for chunk in build_course_chunks([page]) if chunk.kind == "course_extra")

    assert extra.chunk_key == "course:networking#extra-extra-admission-notes"
    assert "valid identification document" in extra.text
    assert extra.metadata["extra_heading"] == "Extra admission notes"


def test_home_import_keeps_partner_content_and_drops_event_sections() -> None:
    page = SourcePage(
        url="https://www.zibeh.ng/",
        path="/",
        title="Home",
        markdown="""# Home

## Events and highlights

This event is not approved for ingestion.

## Our partners and ecosystem

GIZ, SMEDAN and other partners.
""",
        source_hash="source-hash",
    )

    _, chunks, _, _ = build_site_content([page])
    home_text = " ".join(chunk.text for chunk in chunks if chunk.doc_key == "page:home")

    assert "GIZ" in home_text
    assert "event is not approved" not in home_text


def test_repeated_page_headings_get_distinct_chunk_keys() -> None:
    page = SourcePage(
        url="https://www.zibeh.ng/about",
        path="/about",
        title="About",
        markdown="""# About

## Be part of the ZIT community

First approved section.

## Be part of the ZIT community

Second approved section.
""",
        source_hash="source-hash",
    )

    _, chunks, _, _ = build_site_content([page])
    repeated = [chunk for chunk in chunks if chunk.doc_key == "page:about"]

    assert [chunk.chunk_key for chunk in repeated] == [
        "page:about#be-part-of-the-zit-community",
        "page:about#be-part-of-the-zit-community-2",
    ]
    assert "First approved section." in repeated[0].text
    assert "Second approved section." in repeated[1].text


def test_apply_page_uses_the_approved_general_application_link() -> None:
    page = SourcePage(
        url="https://www.zibeh.ng/apply",
        path="/apply",
        title="Apply",
        markdown="# Apply\n\n## How to apply\n\nFollow the application steps.",
        source_hash="source-hash",
    )

    _, chunks, _, _ = build_site_content([page])
    apply_chunk = next(chunk for chunk in chunks if chunk.doc_key == "page:apply")

    assert apply_chunk.metadata["link_keys"] == ["apply:general"]


def test_category_link_keys_follow_generated_category_slugs() -> None:
    link = SourceLink(
        link_key="category:data-and-analytics",
        kind="category",
        label="Courses: data and analytics",
        url="https://www.zibeh.ng/courses?category=data-and-analytics",
    )
    document = SourceDocument(
        doc_key="category:data-analytics",
        doc_type="category",
        title="Data Analytics",
        url_path="/courses",
        source_hash="source-hash",
    )

    links = _canonicalize_category_links({link.link_key: link}, [document])

    assert set(links) == {"category:data-analytics"}
    assert links["category:data-analytics"].url == link.url


def test_manifest_count_mismatch_fails_before_reading_content(tmp_path: Path) -> None:
    export = _write_bundle(tmp_path, "# Test\n")
    manifest_path = export / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["total_candidates"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="total_candidates"):
        load_crawl_import(export, expected_courses=1)


def test_invalid_metadata_is_rejected(tmp_path: Path) -> None:
    export = _write_bundle(tmp_path, "# Test\n")
    metadata_path = export / "metadata.json"
    metadata_path.write_text(json.dumps({"format": "markdown"}), encoding="utf-8")

    with pytest.raises(ValueError, match="metadata has an invalid structure"):
        load_crawl_import(export, expected_courses=1)


def test_payload_hash_changes_when_manifest_decision_changes(tmp_path: Path) -> None:
    export = _write_bundle(tmp_path, "# Test\n")
    first_hash = load_crawl_import(export, expected_courses=1).payload_hash
    manifest_path = export / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["included"] = 0
    manifest["excluded"] = 1
    manifest["items"][0]["decision"] = "excluded"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (export / "https_" / "www.zibeh.ng" / "courses" / "diploma-in-cybersecurity.md").unlink()

    updated = load_crawl_import(export, expected_courses=0)

    assert updated.payload_hash != first_hash
    assert updated.report.direct_pages_loaded == 0


def test_missing_included_page_is_an_error(tmp_path: Path) -> None:
    export = _write_bundle(tmp_path, "# Test\n")
    page_path = export / "https_" / "www.zibeh.ng" / "courses" / "diploma-in-cybersecurity.md"
    page_path.unlink()

    with pytest.raises(ValueError, match="direct pages are missing"):
        load_crawl_import(export, expected_courses=1)


def test_supporting_website_json_counts_only_expected_lists(tmp_path: Path) -> None:
    courses = tmp_path / "courses.json"
    content = tmp_path / "website-content.json"
    courses.write_text(json.dumps([{"title": "A"}]), encoding="utf-8")
    content.write_text(
        json.dumps(
            {
                "courses": [{"title": "A"}],
                "albums": [],
                "events": [],
                "cohorts": [{"name": "C"}],
            }
        ),
        encoding="utf-8",
    )

    assert inspect_supporting_json(courses, content) == {
        "course_catalog_items": 1,
        "website_courses": 1,
        "albums": 0,
        "events": 0,
        "cohorts": 1,
    }


def test_supporting_json_fills_missing_fields_without_overriding_crawl(
    tmp_path: Path,
) -> None:
    export = _write_bundle(
        tmp_path,
        """# Diploma in Cybersecurity

## About the course

Learn practical cyber safety in a focused course for working adults and new learners.
""",
    )
    courses = tmp_path / "courses.json"
    website = tmp_path / "website-content.json"
    record = {
        "title": "Diploma in Cybersecurity",
        "category": "Cybersecurity",
        "duration": "6 Months",
        "description": "A practical cybersecurity course.",
        "skills": ["network safety"],
    }
    courses.write_text(json.dumps([record]), encoding="utf-8")
    website.write_text(json.dumps({"courses": [record]}), encoding="utf-8")

    result = load_crawl_import(
        export,
        expected_courses=1,
        courses_json=courses,
        website_content_json=website,
    )

    facts = next(chunk for chunk in result.chunks if chunk.kind == "course_facts")
    assert "Category: Cybersecurity" in facts.text
    assert "Duration: 6 Months" in facts.text
    assert "A practical cybersecurity course." not in facts.text
    learning = next(chunk for chunk in result.chunks if chunk.kind == "learning_careers")
    assert "Skills you will build: network safety" in learning.text
    assert result.report.source_conflicts == 2
    assert {
        conflict["field"]
        for conflict in result.report.source_conflict_details
        if conflict["code"] == "source_value_conflict"
    } == {"overview"}


def test_supporting_json_conflicts_are_reported_without_arbitrary_fallback(
    tmp_path: Path,
) -> None:
    export = _write_bundle(
        tmp_path,
        """# Diploma in Cybersecurity

## About the course

Learn practical cyber safety in a focused course for working adults and new learners.
""",
    )
    courses = tmp_path / "courses.json"
    website = tmp_path / "website-content.json"
    courses.write_text(
        json.dumps([{"title": "Diploma in Cybersecurity", "category": "Technology"}]),
        encoding="utf-8",
    )
    website.write_text(
        json.dumps(
            {"courses": [{"title": "Diploma in Cybersecurity", "category": "Cybersecurity"}]}
        ),
        encoding="utf-8",
    )

    result = load_crawl_import(
        export,
        expected_courses=1,
        courses_json=courses,
        website_content_json=website,
    )

    facts = next(chunk for chunk in result.chunks if chunk.kind == "course_facts")
    assert "Category:" not in facts.text
    assert result.report.source_conflicts == 1
    assert result.report.source_conflict_details[0]["code"] == "supporting_sources_disagree"


def test_manifest_rejects_non_approved_crawl_id(tmp_path: Path) -> None:
    export = _write_bundle(tmp_path, "# Test\n")
    metadata_path = export / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["crawl_id"] = "another-crawl"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="approved export"):
        load_crawl_import(export, expected_courses=1)
