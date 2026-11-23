from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from app.config import Settings
from app.content.archive import materialize_crawl_archive


def _archive(entries: list[tuple[str, bytes]]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return output.getvalue()


def test_archive_is_materialized_only_inside_temporary_directory() -> None:
    payload = _archive(
        [
            ("manifest.json", b"{}"),
            ("metadata.json", b"{}"),
            ("https_/www.zibeh.ng/about.md", b"# About"),
        ]
    )

    with materialize_crawl_archive(payload, Settings(_env_file=None)) as root:
        assert root.parent == Path(tempfile.gettempdir())
        assert (root / "https_" / "www.zibeh.ng" / "about.md").read_text() == "# About"
    assert not root.exists()


@pytest.mark.parametrize(
    "filename",
    [
        "../outside.md",
        "https_\\..\\outside.md",
        "C:/outside.md",
        "unapproved.txt",
    ],
)
def test_archive_rejects_unsafe_or_unapproved_paths(filename: str) -> None:
    payload = _archive(
        [
            ("manifest.json", b"{}"),
            ("metadata.json", b"{}"),
            (filename, b"unsafe"),
        ]
    )

    with (
        pytest.raises(ValueError, match=r"unsafe path|outside the approved"),
        materialize_crawl_archive(payload, Settings(_env_file=None)),
    ):
        pytest.fail("Invalid archive was accepted")


def test_archive_rejects_duplicate_paths() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr("metadata.json", b"{}")
        archive.writestr("https_/www.zibeh.ng/about.md", b"first")
        archive.writestr("https_/www.zibeh.ng/about.md", b"second")

    with (
        pytest.raises(ValueError, match="duplicate paths"),
        materialize_crawl_archive(output.getvalue(), Settings(_env_file=None)),
    ):
        pytest.fail("Duplicate archive paths were accepted")


def test_archive_rejects_symbolic_links() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr("metadata.json", b"{}")
        link = ZipInfo("https_/www.zibeh.ng/about.md")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archive.writestr(link, b"target")

    with (
        pytest.raises(ValueError, match="Symbolic links"),
        materialize_crawl_archive(output.getvalue(), Settings(_env_file=None)),
    ):
        pytest.fail("Symbolic link was accepted")
