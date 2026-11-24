from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def get(
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, dict[str, str], bytes]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def post(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, dict[str, str], bytes]:
    request_headers = {"Content-Type": "application/json", **headers}
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def stream_chat(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, set[str]]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    events: set[str] = set()
    try:
        with urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line.startswith("event:"):
                    events.add(line.partition(":")[2].strip())
            return response.status, events
    except HTTPError as exc:
        return exc.code, events


def _origin(value: str) -> bool:
    parts = urlsplit(value)
    return (
        parts.scheme in {"http", "https"}
        and bool(parts.netloc)
        and not parts.username
        and not parts.password
        and not parts.path
        and not parts.query
        and not parts.fragment
    )


def _report(name: str, passed: bool, hint: str) -> bool:
    print(f"{'PASS' if passed else 'FAIL'}\t{name}")
    if not passed:
        print(f"HINT\t{hint}")
    return not passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check the deployed assistant API.")
    parser.add_argument("--api", required=True, help="Backend origin, without a path")
    parser.add_argument(
        "--origin",
        default="http://localhost:5173",
        help="Exact browser origin allowed by WIDGET_ORIGINS",
    )
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args(argv)
    if not _origin(args.api) or not _origin(args.origin) or args.timeout <= 0:
        parser.error("--api and --origin must be exact HTTP(S) origins; timeout must be positive")

    api = args.api.rstrip("/")
    headers = {"Origin": args.origin}
    failed = False
    for name, path, hint in (
        ("health", "/api/v1/health", "Check that the backend service is running."),
        ("ready", "/api/v1/ready", "Check DATABASE_URL and the active content release."),
    ):
        try:
            status, _, _ = get(f"{api}{path}", headers, args.timeout)
        except (URLError, TimeoutError):
            status = 0
        failed |= _report(name, 200 <= status < 300, hint)

    try:
        status, response_headers, body = get(f"{api}/api/v1/config", headers, args.timeout)
        config = json.loads(body) if 200 <= status < 300 else {}
        cors_origin = next(
            (
                value
                for key, value in response_headers.items()
                if key.lower() == "access-control-allow-origin"
            ),
            None,
        )
        failed |= _report(
            "config-and-cors",
            isinstance(config, dict)
            and config.get("enabled") is True
            and cors_origin == args.origin,
            "Check rollout, kill switch, and exact WIDGET_ORIGINS entry.",
        )
    except (URLError, TimeoutError, json.JSONDecodeError):
        failed |= _report(
            "config-and-cors",
            False,
            "Check API reachability and exact WIDGET_ORIGINS entry.",
        )

    session_token: str | None = None
    try:
        status, _, body = post(
            f"{api}/api/v1/sessions",
            {"turnstile_token": None},
            headers,
            args.timeout,
        )
        response = json.loads(body) if 200 <= status < 300 else {}
        value = response.get("session_token") if isinstance(response, dict) else None
        session_token = value if status in {200, 201} and isinstance(value, str) and value else None
    except (URLError, TimeoutError, json.JSONDecodeError):
        session_token = None
    failed |= _report(
        "session",
        session_token is not None,
        "Check rollout, TURNSTILE_ENABLED, and session settings.",
    )

    if session_token is not None:
        try:
            status, events = stream_chat(
                f"{api}/api/v1/chat/stream",
                {
                    "message": "How do I contact ZIT Admissions?",
                    "session_token": session_token,
                },
                headers,
                max(args.timeout, 30),
            )
        except (URLError, TimeoutError):
            status, events = 0, set()
        failed |= _report(
            "chat-stream",
            200 <= status < 300
            and "delta" in events
            and "done" in events
            and "error" not in events,
            "Check the chat stream, active release, and provider configuration.",
        )
    else:
        failed |= _report(
            "chat-stream",
            False,
            "Resolve the session check first; no chat request was sent.",
        )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
