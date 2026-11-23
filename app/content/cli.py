from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.content.importer import inspect_supporting_json, load_crawl_import, report_as_dict

_EXPORT_DIR = Path("misc/export-90e627d02de849b28ffe2ae9996a12ca")
_WEBSITE_DIR = Path("misc/zit-website")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.content.cli")
    parser.add_argument("command", choices=("dry-run",))
    parser.add_argument("--export-dir", type=Path, default=_EXPORT_DIR)
    parser.add_argument("--courses-json", type=Path, default=_WEBSITE_DIR / "src/data/courses.json")
    parser.add_argument(
        "--website-content-json",
        type=Path,
        default=_WEBSITE_DIR / "content/website-content.json",
    )
    args = parser.parse_args()
    try:
        crawl = load_crawl_import(
            args.export_dir,
            courses_json=args.courses_json,
            website_content_json=args.website_content_json,
        )
        support_counts = inspect_supporting_json(args.courses_json, args.website_content_json)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "mode": args.command,
                "database_written": False,
                "embedding_requests_made": False,
                "provider_calls_allowed": False,
                "payload_hash": crawl.payload_hash,
                "crawl": report_as_dict(crawl.report),
                "warnings": crawl.warnings,
                "supporting_website_data": support_counts,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
