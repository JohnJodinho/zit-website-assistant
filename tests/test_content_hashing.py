from dataclasses import replace
from pathlib import Path

from app.content.hashing import hash_content
from app.content.importer import _complete_payload_hash
from app.content.models import ContentChunk
from app.content.sources import SourceReconciliation


def test_content_hash_includes_metadata_and_embedding_text() -> None:
    text_hash = hash_content("fact", None, {"title": "A"})

    assert text_hash != hash_content("fact", None, {"title": "B"})
    assert text_hash != hash_content("fact", "query terms", {"title": "A"})


def test_import_payload_hash_includes_generated_chunk_keys(tmp_path: Path) -> None:
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")
    chunk = ContentChunk(
        chunk_key="page:about#section",
        doc_key="page:about",
        kind="section",
        text="About",
        token_count=2,
        content_hash="content-hash",
        metadata={},
    )
    reconciliation = SourceReconciliation({}, (), (), None)
    original = _complete_payload_hash(tmp_path, "source-hash", reconciliation, (), (chunk,), ())
    changed = _complete_payload_hash(
        tmp_path,
        "source-hash",
        reconciliation,
        (),
        (replace(chunk, chunk_key="page:about#section-2"),),
        (),
    )

    assert changed != original
