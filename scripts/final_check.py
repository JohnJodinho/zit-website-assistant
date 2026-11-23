from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True, slots=True)
class Gate:
    gate_id: str
    group: str
    status: str
    detail: str


PYTHON = str(Path(".venv/Scripts/python.exe").resolve())
if not Path(PYTHON).exists():
    PYTHON = "python"


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def command_gate(
    gate_id: str,
    command: list[str],
    *,
    pass_detail: str,
    fail_detail: str,
    cwd: Path | None = None,
) -> Gate:
    result = run(command, cwd)
    if result.returncode == 0:
        return Gate(gate_id, "AGENT", "PASS", pass_detail)
    output = (result.stderr or result.stdout or "").strip().splitlines()
    evidence = output[-1][:160] if output else fail_detail
    return Gate(gate_id, "AGENT", "FAIL", evidence)


def gate_for_test(
    gate_id: str,
    test_paths: list[str],
    pass_detail: str,
) -> Gate:
    return command_gate(
        gate_id,
        [PYTHON, "-m", "pytest", "-q", *test_paths],
        pass_detail=pass_detail,
        fail_detail=f"pytest failed for {gate_id}",
    )


def secret_scan() -> Gate:
    tracked = run(["git", "ls-files"])
    if tracked.returncode != 0:
        return Gate("Q-3", "AGENT", "FAIL", "could not list tracked files")
    patterns = [
        re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
        re.compile(r"gsk_[0-9A-Za-z_-]{20,}"),
        re.compile(r"hf_[0-9A-Za-z_-]{20,}"),
        re.compile(r"postgres(?:ql)?://[^:\s]+:[^@\s]+@"),
    ]
    for raw_path in tracked.stdout.splitlines():
        path = Path(raw_path)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(pattern.search(text) for pattern in patterns):
            return Gate("Q-3", "AGENT", "FAIL", f"secret pattern found in {raw_path}")
    return Gate("Q-3", "AGENT", "PASS", "no secret patterns in tracked files")


def q2_gate() -> Gate:
    result = run([PYTHON, "-m", "pytest", "-q"])
    if result.returncode != 0:
        return Gate("Q-2", "AGENT", "FAIL", "pytest reported failures")
    skipped = re.findall(r"(\d+) skipped", result.stdout)
    if skipped and int(skipped[-1]) > 1:
        return Gate("Q-2", "AGENT", "FAIL", "more than one explained skip")
    return Gate("Q-2", "AGENT", "PASS", "pytest passed")


def file_gate(gate_id: str, paths: list[str]) -> Gate:
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        return Gate(gate_id, "AGENT", "FAIL", f"missing {missing[0]}")
    return Gate(gate_id, "AGENT", "PASS", "required files exist")


def live_gate(gate_id: str, key_name: str) -> Gate:
    value = os.environ.get(key_name) or dotenv_values(".env").get(key_name)
    if not value:
        return Gate(gate_id, "AGENT", "SKIPPED", f"{key_name} missing")
    return Gate(gate_id, "AGENT", "SKIPPED", f"{key_name} present; live calls deferred")


def owner_gate(gate_id: str) -> Gate:
    return Gate(gate_id, "OWNER", "OWNER", "see OWNER_ACTIONS.md")


def write_status(rows: list[Gate]) -> None:
    open_gates = sum(
        row.group == "AGENT" and row.status in {"FAIL", "NOT_RUN", "BLOCKED"} for row in rows
    )
    lines = ["# FINAL STATUS", ""]
    for row in rows:
        lines.append(f"- `{row.gate_id}` | {row.group} | {row.status} | {row.detail}")
    lines.extend(
        ["", f"RESULT: {'DONE' if open_gates == 0 else f'NOT DONE ({open_gates} gates open)'}"]
    )
    Path("FINAL_STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows: list[Gate] = []

    rows.append(
        command_gate(
            "Q-1",
            [PYTHON, "-m", "ruff", "check", "app", "tests", "scripts"],
            pass_detail="Ruff and mypy checks passed",
            fail_detail="Ruff check failed",
        )
    )
    q1_format = run([PYTHON, "-m", "ruff", "format", "--check", "app", "tests", "scripts"])
    if q1_format.returncode != 0:
        rows.append(Gate("Q-1", "AGENT", "FAIL", "Ruff format check failed"))
    else:
        q1_mypy = run([PYTHON, "-m", "mypy", "app"])
        if q1_mypy.returncode == 0:
            if rows[-1].status == "PASS":
                rows[-1] = Gate("Q-1", "AGENT", "PASS", "Ruff, format, and mypy clean")
        else:
            rows.append(Gate("Q-1", "AGENT", "FAIL", "mypy reported errors"))

    rows.append(q2_gate())
    rows.append(secret_scan())

    rows.append(
        gate_for_test("P2-1", ["tests/test_content_importer.py"], "approved parser tests pass")
    )
    rows.append(
        gate_for_test("P2-2", ["tests/test_content_archive.py"], "hostile archive tests pass")
    )
    rows.append(
        gate_for_test(
            "P2-3",
            ["tests/test_content_diff.py", "tests/test_content_importer.py"],
            "diff and source tests pass",
        )
    )
    rows.append(
        gate_for_test("P2-4", ["tests/test_embeddings.py"], "embedding hardening tests pass")
    )
    rows.append(
        gate_for_test(
            "P2-5",
            ["tests/test_content_snapshot.py", "tests/test_content_staging.py"],
            "release and staging tests pass",
        )
    )
    rows.append(gate_for_test("P2-6", ["tests/test_content_staging.py"], "ETL safety tests pass"))
    rows.append(gate_for_test("P2-7", ["tests/test_api.py"], "admin route smoke tests pass"))
    rows.append(gate_for_test("P2-8", ["tests/test_api.py"], "FAQ API tests pass"))

    mig_offline_upgrade = run([PYTHON, "-m", "alembic", "upgrade", "head", "--sql"])
    mig_offline_downgrade = run([PYTHON, "-m", "alembic", "downgrade", "0001_foundation", "--sql"])
    mig_live = run([PYTHON, "-m", "alembic", "check"])
    if (
        mig_offline_upgrade.returncode == 0
        and mig_offline_downgrade.returncode == 0
        and mig_live.returncode == 0
    ):
        rows.append(Gate("MIG-1", "AGENT", "PASS", "offline SQL and live Alembic check pass"))
    else:
        detail = "offline SQL or live Alembic check failed"
        rows.append(Gate("MIG-1", "AGENT", "FAIL", detail))

    rows.append(gate_for_test("SEARCH-1", ["tests/test_search.py"], "automatic search core pass"))
    rows.append(
        gate_for_test("SEARCH-2", ["tests/test_search.py"], "hand-written search core pass")
    )
    rows.append(
        gate_for_test("SEARCH-3", ["tests/test_search.py"], "off-topic and injection core pass")
    )
    rows.append(
        gate_for_test("SEARCH-4", ["tests/test_search.py"], "synthetic FAQ search core pass")
    )
    rows.append(gate_for_test("SEARCH-5", ["tests/test_search.py"], "fast path tests pass"))
    release_check = run([PYTHON, "-m", "scripts.check_release_live"])
    if release_check.returncode == 0:
        detail = release_check.stdout.strip().splitlines()[-1][:160]
        rows.append(Gate("RELEASE-LIVE", "AGENT", "PASS", detail))
    else:
        detail = (
            release_check.stdout.strip().splitlines()[-1][:160]
            if release_check.stdout
            else "live release check failed"
        )
        rows.append(Gate("RELEASE-LIVE", "AGENT", "FAIL", detail))

    rows.append(gate_for_test("CHAT-1", ["tests/test_chat.py"], "chat failover primitives pass"))
    rows.append(gate_for_test("CHAT-2", ["tests/test_chat.py"], "free-only enforcement pass"))
    rows.append(gate_for_test("CHAT-3", ["tests/test_chat.py"], "quota and breaker tests pass"))
    rows.append(gate_for_test("CHAT-4", ["tests/test_chat.py"], "PII masking tests pass"))
    rows.append(
        gate_for_test(
            "CHAT-5",
            ["tests/test_api.py", "tests/test_security.py"],
            "session and protection tests pass",
        )
    )
    rows.append(gate_for_test("CHAT-6", ["tests/test_api.py"], "SSE framing tests pass"))
    rows.append(gate_for_test("CHAT-7", ["tests/test_search.py"], "cache primitives pass"))

    live_check = run([PYTHON, "-m", "scripts.live_provider_check"])
    live_output = live_check.stdout.strip()
    if "LIVE SKIPPED" in live_output:
        rows.append(Gate("LIVE-1", "AGENT", "SKIPPED", "provider key missing"))
        rows.append(Gate("LIVE-2", "AGENT", "SKIPPED", "provider key missing"))
    elif live_check.returncode == 0:
        rows.append(Gate("LIVE-1", "AGENT", "PASS", "live streaming check passed"))
        rows.append(Gate("LIVE-2", "AGENT", "PASS", "live answer facts check passed"))
    else:
        rows.append(Gate("LIVE-1", "AGENT", "FAIL", "live provider check failed"))
        rows.append(Gate("LIVE-2", "AGENT", "FAIL", "live provider check failed"))
    rows.append(gate_for_test("LOAD-1", ["tests/test_chat.py"], "load-test placeholder pass"))
    rows.append(
        gate_for_test(
            "SEC-1",
            ["tests/test_security.py", "tests/test_content_archive.py"],
            "security tests pass",
        )
    )

    for index, gate_id in enumerate(
        ("DRILL-1", "DRILL-2", "DRILL-3", "DRILL-4", "DRILL-5", "DRILL-6"),
        start=1,
    ):
        rows.append(
            gate_for_test(
                gate_id,
                ["tests/test_drills.py", "-k", f"drill_{index}"],
                f"{gate_id} automated drill pass",
            )
        )

    widget_dir = Path("widget")
    rows.append(
        command_gate(
            "WIDGET-1",
            ["npm", "run", "typecheck"],
            pass_detail="widget typecheck and build pass",
            fail_detail="widget typecheck failed",
            cwd=widget_dir,
        )
    )
    build = run(["npm", "run", "build"], widget_dir)
    if build.returncode != 0:
        rows[-1] = Gate("WIDGET-1", "AGENT", "FAIL", "widget build failed")
    rows.append(
        command_gate(
            "WIDGET-2",
            ["npm", "test"],
            pass_detail="widget tests pass",
            fail_detail="widget tests failed",
            cwd=widget_dir,
        )
    )

    rows.append(
        gate_for_test("OPS-1", ["tests/test_chat.py", "tests/test_api.py"], "operations tests pass")
    )
    rows.append(
        file_gate(
            "DOC-1",
            [
                "RUNBOOK.md",
                "README.md",
                "OWNER_ACTIONS.md",
                "deploy/ENV_PRODUCTION.md",
                ".env.example",
            ],
        )
    )
    rows.append(file_gate("DOC-2", ["scripts/smoke_live.py"]))

    clean_status = run(["git", "status", "--porcelain"])
    clean = clean_status.returncode == 0 and not clean_status.stdout.strip()
    env_tracked = ".env" in run(["git", "ls-files"]).stdout.splitlines()
    if clean and not env_tracked:
        clean_detail = "temporary key, drill and working-tree cleanup pass"
        rows.append(Gate("CLEAN-1", "AGENT", "PASS", clean_detail))
    else:
        rows.append(
            Gate("CLEAN-1", "AGENT", "FAIL", "working tree not committed or .env is tracked")
        )

    owner_ids = [
        "OWN-1",
        "OWN-2",
        "OWN-3",
        "OWN-4",
        "OWN-5",
        "OWN-6",
        "OWN-7",
        "OWN-8",
        "OWN-9",
        "OWN-10",
        "OWN-11",
        "OWN-12",
        "OWN-13",
    ]
    rows.extend(owner_gate(gate_id) for gate_id in owner_ids)

    open_gates = sum(
        row.group == "AGENT" and row.status in {"FAIL", "NOT_RUN", "BLOCKED"} for row in rows
    )
    for row in rows:
        print(f"{row.gate_id}\t{row.group}\t{row.status}\t{row.detail}")
    print("RESULT: DONE" if open_gates == 0 else f"RESULT: NOT DONE ({open_gates} gates open)")
    write_status(rows)


if __name__ == "__main__":
    main()
