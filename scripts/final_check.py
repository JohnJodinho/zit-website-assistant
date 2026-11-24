from __future__ import annotations

import ast
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


PYTHON = str(Path("venv/Scripts/python.exe").resolve())
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
        re.compile(r"postgres(?:ql)?://[^:\s]+:[^<@\s][^@\s]*@"),
    ]
    for raw_path in tracked.stdout.splitlines():
        path = Path(raw_path)
        if not path.is_file():
            continue
        if raw_path.startswith("tests/"):
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


def docs_gate() -> Gate:
    required = [
        "README.md",
        "RUNBOOK.md",
        "API_CONTRACT.md",
        "OWNER_ACTIONS.md",
        "deploy/ENV_PRODUCTION.md",
        ".env.example",
    ]
    missing = [path for path in required if not Path(path).is_file()]
    if missing:
        return Gate("DOC-1", "AGENT", "FAIL", f"missing {missing[0]}")

    config = ast.parse(Path("app/config.py").read_text(encoding="utf-8"))
    settings_class = next(
        node for node in config.body if isinstance(node, ast.ClassDef) and node.name == "Settings"
    )
    variables = {
        statement.target.id.upper()
        for statement in settings_class.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    }
    example_variables = {
        line.split("=", 1)[0].strip()
        for line in Path(".env.example").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    production_text = Path("deploy/ENV_PRODUCTION.md").read_text(encoding="utf-8")
    production_variables = set(re.findall(r"`([A-Z][A-Z0-9_]*)`", production_text))
    missing_example = sorted(variables - example_variables)
    missing_production = sorted(variables - production_variables)
    if missing_example:
        return Gate("DOC-1", "AGENT", "FAIL", f"{missing_example[0]} missing from .env.example")
    if missing_production:
        return Gate(
            "DOC-1",
            "AGENT",
            "FAIL",
            f"{missing_production[0]} missing from deploy/ENV_PRODUCTION.md",
        )
    return Gate("DOC-1", "AGENT", "PASS", "backend docs exist and cover every Settings variable")


def api_contract_gate() -> Gate:
    path = Path("API_CONTRACT.md")
    if not path.is_file():
        return Gate("DOC-3", "AGENT", "FAIL", "API_CONTRACT.md is missing")
    contract = path.read_text(encoding="utf-8")
    required_routes = (
        "GET /config",
        "POST /sessions",
        "POST /chat/stream",
        "POST /feedback",
        "POST /client-events",
        "GET /health",
        "GET /ready",
    )
    missing_routes = [route for route in required_routes if route not in contract]
    required_events = ("`ping`", "`meta`", "`delta`", "`error`", "`done`")
    missing_events = [event for event in required_events if event not in contract]
    if missing_routes:
        return Gate("DOC-3", "AGENT", "FAIL", f"missing route {missing_routes[0]}")
    if missing_events or "partial" not in contract or "curl -N" not in contract:
        return Gate(
            "DOC-3", "AGENT", "FAIL", "stream events, partial handling, or curl example missing"
        )
    return Gate("DOC-3", "AGENT", "PASS", "all public routes and SSE contract are documented")


def clean_gate() -> Gate:
    database_check = run([PYTHON, "-m", "scripts.check_publish_rollback", "--verify"])
    if database_check.returncode != 0:
        return Gate("CLEAN-1", "AGENT", "FAIL", "shared-database drill cleanup verification failed")

    status = run(["git", "status", "--porcelain", "--untracked-files=all"])
    if status.returncode != 0:
        return Gate("CLEAN-1", "AGENT", "FAIL", "could not inspect the working tree")
    preserved_paths = {
        "BACKEND_ONLY.md",
        "copilot-instructions.md",
        ".github/copilot-instructions.md",
        "FINAL_STATUS.md",
        "scripts/db_test.py",
    }
    dirty_paths = set()
    for line in status.stdout.splitlines():
        path = line[3:].strip().replace("\\", "/")
        if " -> " in path:
            path = path.rsplit(" -> ", maxsplit=1)[-1]
        if not path.startswith("widget/") and path not in preserved_paths:
            dirty_paths.add(path)
    env_tracked = ".env" in run(["git", "ls-files"]).stdout.splitlines()
    if dirty_paths or env_tracked:
        detail = "backend worktree changes remain" if dirty_paths else ".env is tracked"
        return Gate("CLEAN-1", "AGENT", "FAIL", detail)
    return Gate(
        "CLEAN-1",
        "AGENT",
        "PASS",
        "shared database clean; backend changes committed; out-of-scope work preserved",
    )


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
            [
                PYTHON,
                "-m",
                "ruff",
                "check",
                "app",
                "tests",
                "scripts",
                "--extend-exclude",
                "scripts/db_test.py",
            ],
            pass_detail="Ruff and mypy checks passed",
            fail_detail="Ruff check failed",
        )
    )
    q1_format = run(
        [
            PYTHON,
            "-m",
            "ruff",
            "format",
            "--check",
            "app",
            "tests",
            "scripts",
            "--extend-exclude",
            "scripts/db_test.py",
        ]
    )
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
    mig_offline_downgrade = run([PYTHON, "-m", "alembic", "downgrade", "0002:0001", "--sql"])
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
    rows.append(
        command_gate(
            "CHAT-DB",
            [PYTHON, "-m", "scripts.check_chat_db"],
            pass_detail="shared Supabase chat persistence proof passed",
            fail_detail="shared Supabase chat persistence proof failed",
        )
    )

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
    rows.append(
        gate_for_test(
            "LOAD-1",
            [
                "tests/test_chat_streaming.py",
                "-k",
                "ten_fake_provider_streams_complete_concurrently",
            ],
            "10 concurrent fake-provider streams pass",
        )
    )
    rows.append(
        gate_for_test(
            "SEC-1",
            ["tests/test_security.py", "tests/test_content_archive.py"],
            "security tests pass",
        )
    )

    rows.append(
        gate_for_test(
            "DRILL-1",
            ["tests/test_admin_audit_integration.py"],
            "marked tracing and admin audit drill passes",
        )
    )
    rows.append(
        gate_for_test(
            "DRILL-2",
            ["tests/test_drills.py", "-k", "drill_2"],
            "five synthetic FAQ cases pass",
        )
    )
    rows.append(
        command_gate(
            "DRILL-6",
            [PYTHON, "-m", "scripts.check_publish_rollback", "--verify"],
            pass_detail="publish/rollback drill cleanup verified",
            fail_detail="publish/rollback drill verification failed",
        )
    )

    rows.append(
        gate_for_test(
            "OPS-1",
            ["tests/test_ops.py", "tests/test_ops_routes.py"],
            "retention and reduced operations tests pass",
        )
    )
    rows.append(
        gate_for_test(
            "DOC-2",
            ["tests/test_smoke_live.py"],
            "API smoke script tests pass",
        )
    )
    rows.append(docs_gate())
    rows.append(api_contract_gate())
    rows.append(clean_gate())

    owner_ids = ["OWN-1", "OWN-2", "OWN-3", "OWN-4"]
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
