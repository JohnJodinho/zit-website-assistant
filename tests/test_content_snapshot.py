from uuid import uuid4

from app.config import Settings
from app.content.snapshot import validate_release_content
from app.db.models import Chunk, Link
from app.embeddings.client import BGE_MODEL_ID


def _chunk(
    *,
    chunk_key: str = "course:networking#facts",
    doc_key: str = "course:networking",
    embedding: list[float] | None = None,
    embedding_model: str = BGE_MODEL_ID,
    metadata: dict[str, object] | None = None,
) -> Chunk:
    vector = embedding if embedding is not None else [1.0, *([0.0] * 767)]
    return Chunk(
        id=uuid4(),
        chunk_key=chunk_key,
        doc_key=doc_key,
        version=1,
        kind="course_facts",
        origin="etl",
        text="Course facts for networking.",
        token_count=12,
        metadata_json=metadata or {"link_keys": ["course:networking", "apply:networking"]},
        content_hash="content-hash",
        embedding=vector,
        embedding_model=embedding_model,
        created_by="test",
        created_via="etl",
    )


def _link(link_key: str, url: str) -> Link:
    return Link(
        id=uuid4(),
        link_key=link_key,
        version=1,
        kind="page",
        label=link_key,
        url=url,
        description="",
        aliases=[],
        priority=50,
        active=True,
        origin="etl",
        created_by="test",
    )


def _course_links() -> list[Link]:
    return [
        _link("course:networking", "https://www.zibeh.ng/courses/networking"),
        _link("apply:networking", "https://www.zibeh.ng/apply?course=networking"),
        _link("contact:admissions", "https://www.zibeh.ng/contact"),
    ]


def test_release_content_accepts_normalized_bge_and_required_links() -> None:
    result = validate_release_content([_chunk()], _course_links(), Settings(_env_file=None))

    assert result.valid
    assert result.errors == ()


def test_release_content_rejects_bad_embedding_and_unresolved_link() -> None:
    chunk = _chunk(
        embedding=[0.0] * 768,
        metadata={"link_keys": ["course:missing"]},
    )

    result = validate_release_content([chunk], _course_links(), Settings(_env_file=None))

    codes = {error["code"] for error in result.errors}
    assert codes >= {"embedding_invalid", "unknown_chunk_link_key"}


def test_release_content_rejects_unsafe_link_hosts() -> None:
    links = _course_links()
    links[0] = _link("course:networking", "https://example.com/courses/networking")

    result = validate_release_content([_chunk()], links, Settings(_env_file=None))

    assert any(error["code"] == "invalid_link_url" for error in result.errors)
