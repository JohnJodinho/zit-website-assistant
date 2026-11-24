from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

from app.api.admin.ops_routes import SettingPatch, patch_setting
from app.config import Settings
from app.db.models import AuditLog, Setting
from app.main import create_app
from app.security.keys import AdminPrincipal, AdminScope
from fastapi.testclient import TestClient


class FakeSession:
    def __init__(self) -> None:
        self.setting = Setting(
            key="KILL_SWITCH",
            value={"value": False},
            updated_by="owner",
        )
        self.added: list[object] = []
        self.committed = False

    async def get(self, model: type[Setting], key: str) -> Setting | None:
        assert model is Setting
        return self.setting if key == self.setting.key else None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True


def test_backend_ops_route_set_matches_reduced_scope() -> None:
    app = create_app(Settings(_env_file=None))
    required = (
        ("GET", "/admin/v1/traces"),
        ("GET", f"/admin/v1/traces/{UUID(int=1)}"),
        ("GET", "/admin/v1/errors"),
        ("GET", "/admin/v1/llm-calls"),
        ("GET", "/admin/v1/settings"),
        ("PATCH", "/admin/v1/settings/KILL_SWITCH"),
        ("GET", "/admin/v1/api-keys"),
        ("POST", "/admin/v1/api-keys"),
        ("DELETE", f"/admin/v1/api-keys/{UUID(int=1)}"),
        ("GET", "/admin/v1/audit"),
    )
    removed = (
        ("GET", "/admin/v1/metrics/summary"),
        ("POST", "/admin/v1/alerts/test"),
        ("DELETE", f"/admin/v1/sessions/{UUID(int=1)}"),
    )

    with TestClient(app) as client:
        for method, path in required:
            assert client.request(method, path).status_code != 404
        for method, path in removed:
            assert client.request(method, path).status_code == 404


def test_setting_patch_is_persisted_and_audited() -> None:
    trace_id = UUID(int=7)
    request = SimpleNamespace(state=SimpleNamespace(trace_id=trace_id))
    session = FakeSession()
    principal = AdminPrincipal(UUID(int=1), "drill", frozenset({AdminScope.WRITE.value}))

    result = asyncio.run(
        patch_setting(
            "KILL_SWITCH",
            SettingPatch(value={"value": True}),
            request,
            session,
            principal,
        )
    )

    audit = next(item for item in session.added if isinstance(item, AuditLog))
    assert result == {
        "key": "KILL_SWITCH",
        "before": {"value": False},
        "value": {"value": True},
    }
    assert session.setting.value == {"value": True}
    assert audit.action == "settings.patch"
    assert audit.target == "KILL_SWITCH"
    assert audit.trace_id == trace_id
    assert session.committed is True
