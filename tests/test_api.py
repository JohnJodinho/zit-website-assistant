from collections.abc import Iterator
from uuid import UUID

import pytest
from app.api.deps import get_admin_principal
from app.config import Settings
from app.db.session import get_db_session
from app.main import create_app
from app.security.keys import AdminPrincipal, AdminScope
from fastapi.testclient import TestClient
from pydantic import SecretStr


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(_env_file=None))) as test_client:
        yield test_client


def test_health_returns_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    UUID(response.headers["X-Request-ID"])


def test_readiness_reports_missing_database_and_unpublished_release(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    assert response.json()["release"] == "not_loaded"


def test_http_errors_use_common_shape_and_request_id(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    body = response.json()

    assert response.status_code == 404
    assert body["error"]["trace_id"] == response.headers["X-Request-ID"]
    assert body["error"]["code"]


def test_admin_docs_are_disabled_by_default(client: TestClient) -> None:
    assert client.get("/admin/docs").status_code == 404
    assert client.get("/docs").status_code == 404


def test_admin_docs_require_http_basic_credentials() -> None:
    settings = Settings(
        _env_file=None,
        public_docs_enabled=True,
        admin_docs_username=SecretStr("owner"),
        admin_docs_password=SecretStr("private"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/admin/docs")
        assert response.status_code == 401, response.text
        assert client.get("/admin/openapi.json").status_code == 401

        response = client.get("/admin/docs", auth=("owner", "private"))
        assert response.status_code == 200
        assert "/admin/openapi.json" in response.text


def test_validation_error_does_not_echo_submitted_values() -> None:
    app = create_app(Settings(_env_file=None))

    async def session_override():
        yield None

    def principal_override() -> AdminPrincipal:
        return AdminPrincipal(UUID(int=1), "test", frozenset({AdminScope.KEYS.value}))

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_admin_principal] = principal_override

    with TestClient(app) as isolated_client:
        response = isolated_client.post(
            "/admin/v1/api-keys",
            json={"name": "private-value", "scopes": ["invalid"]},
        )

    assert response.status_code == 422
    assert "private-value" not in response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_phase_two_routes_are_registered_without_public_chat() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        for path in (
            "/admin/v1/etl/runs",
            "/admin/v1/documents",
            "/admin/v1/chunks",
            "/admin/v1/links",
            "/admin/v1/faqs",
            "/admin/v1/releases",
        ):
            assert client.get(path).status_code == 503
        assert client.get("/api/v1/chat").status_code == 404


def test_publish_stays_blocked_until_search_evaluation_exists() -> None:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_admin_principal] = lambda: AdminPrincipal(
        UUID(int=1),
        "test",
        frozenset({AdminScope.PUBLISH.value}),
    )

    with TestClient(app) as client:
        response = client.post("/admin/v1/releases/1/publish")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "search_evaluation_unavailable"
