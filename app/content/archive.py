from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path, PurePosixPath

from app.config import Settings

_SUPPORTING_JSON = {
    "content/website-content.json",
    "courses.json",
    "src/data/courses.json",
    "website-content.json",
}
_MAX_EXPANSION_FACTOR = 5


@contextmanager
def materialize_crawl_archive(
    payload: bytes,
    settings: Settings,
) -> Iterator[Path]:
    max_zip_bytes = settings.etl_max_zip_mb * 1024 * 1024
    if not payload or len(payload) > max_zip_bytes:
        raise ValueError(f"ZIP upload must be between 1 byte and {settings.etl_max_zip_mb} MB")

    with tempfile.TemporaryDirectory(prefix="zit-crawl-") as directory:
        root = Path(directory).resolve()
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                _validate_archive(archive, settings)
                _extract_archive(archive, root)
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise ValueError("Unable to read a valid crawl ZIP archive") from exc

        if not (root / "manifest.json").is_file() or not (root / "metadata.json").is_file():
            raise ValueError("Crawl ZIP must include root manifest.json and metadata.json")
        yield root


def _validate_archive(archive: zipfile.ZipFile, settings: Settings) -> None:
    entries = archive.infolist()
    files = [entry for entry in entries if not entry.is_dir()]
    _validate_archive_size(files, settings)
    _validate_archive_entries(entries, settings)


def _validate_archive_size(files: list[zipfile.ZipInfo], settings: Settings) -> None:
    if not files or len(files) > settings.etl_max_zip_files:
        raise ValueError(f"ZIP must contain at most {settings.etl_max_zip_files} files")
    total_size = sum(entry.file_size for entry in files)
    if total_size > settings.etl_max_zip_mb * 1024 * 1024 * _MAX_EXPANSION_FACTOR:
        raise ValueError("ZIP expands beyond the allowed size")


def _validate_archive_entries(
    entries: list[zipfile.ZipInfo],
    settings: Settings,
) -> None:
    paths: set[str] = set()
    for entry in entries:
        path = _safe_archive_path(entry)
        if entry.is_dir():
            continue
        normalized = path.as_posix().casefold()
        if normalized in paths:
            raise ValueError("ZIP contains duplicate paths")
        paths.add(normalized)
        if not _is_allowed_path(path):
            raise ValueError("ZIP contains a file outside the approved crawl and JSON inputs")
        _validate_archive_member(entry, settings)


def _validate_archive_member(entry: zipfile.ZipInfo, settings: Settings) -> None:
    if entry.flag_bits & 0x1:
        raise ValueError("Encrypted ZIP files are not allowed")
    if entry.file_size > settings.etl_max_zip_mb * 1024 * 1024:
        raise ValueError("A ZIP member exceeds the allowed size")
    if entry.compress_size == 0 and entry.file_size:
        raise ValueError("ZIP contains an invalid compressed member")
    if entry.compress_size and entry.file_size / entry.compress_size > 1000:
        raise ValueError("ZIP contains an unsafe compression ratio")
    mode = entry.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ValueError("Symbolic links are not allowed in crawl ZIP files")


def _safe_archive_path(entry: zipfile.ZipInfo) -> PurePosixPath:
    name = entry.filename
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or ":" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("ZIP contains an unsafe path")
    return path


def _is_allowed_path(path: PurePosixPath) -> bool:
    name = path.as_posix()
    if name in {"manifest.json", "metadata.json"} | _SUPPORTING_JSON:
        return True
    if name.startswith("https_/www.zibeh.ng/") and path.suffix.lower() == ".md":
        return True
    return name == "https_/www.zibeh.ng.md"


def _extract_archive(archive: zipfile.ZipFile, root: Path) -> None:
    for entry in archive.infolist():
        relative = _safe_archive_path(entry)
        destination = (root / Path(*relative.parts)).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("ZIP path escapes the temporary extraction directory")
        if entry.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(entry) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target, length=64 * 1024)
