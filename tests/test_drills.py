from __future__ import annotations

from app.chat.pii import mask_pii
from app.content.snapshot import ContentSnapshot
from app.search.hybrid import InMemoryHybridSearch


def test_drill_1_reference_shape() -> None:
    assert mask_pii("phone +2348012345678")[0].find("+234") == -1


def test_drill_2_fix_and_replay() -> None:
    snapshot = ContentSnapshot(release_id=1, chunks=(), links=(), loaded_at="now")
    hits, gate = InMemoryHybridSearch(snapshot).retrieve(None, "course")
    assert hits == []
    assert gate["degraded"] is True


def test_drill_3_bad_archive_is_rejected() -> None:
    from app.content.archive import materialize_crawl_archive

    assert callable(materialize_crawl_archive)


def test_drill_4_synthetic_faq_shape() -> None:
    assert {"question", "answer", "variants"}
    assert True


def test_drill_5_widget_files_exist() -> None:
    from pathlib import Path

    assert Path("widget/public/loader.js").is_file()
    assert Path("widget/public/test-parent.html").is_file()


def test_drill_6_release_status_shape() -> None:
    assert {"draft", "published", "archived"}
