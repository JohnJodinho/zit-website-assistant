from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()
    except URLError as exc:
        print(f"FAIL\tnetwork\t{type(exc.reason).__name__}")
        raise


def post(url: str, payload: dict[str, object]) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--widget", required=True)
    args = parser.parse_args()
    api = args.api.rstrip("/")
    widget = args.widget.rstrip("/")
    failed = False
    checks = [
        ("health", f"{api}/api/v1/health", "Use the backend /health fix hint"),
        ("ready", f"{api}/api/v1/ready", "Check DATABASE_URL and active release"),
        ("config", f"{api}/api/v1/config", "Check rollout and kill-switch settings"),
    ]
    for name, url, hint in checks:
        try:
            status, _, _body = get(url)
            if status < 400:
                print(f"PASS\t{name}")
            else:
                failed = True
                print(f"FAIL\t{name}\t{hint}")
        except URLError:
            failed = True
            print(f"FAIL\t{name}\tnetwork\t{hint}")
    status, _, _body = get(widget)
    if status < 400:
        print("PASS\twidget")
    else:
        failed = True
        print("FAIL\twidget\tCheck the Vercel URL")
    try:
        status, _, _body = post(f"{api}/api/v1/sessions", {"turnstile_token": None})
        if status in {200, 201}:
            print("PASS\tsession")
        else:
            failed = True
            print("FAIL\tsession\tCheck session settings")
    except URLError:
        failed = True
        print("FAIL\tsession\tCheck network")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
