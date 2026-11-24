from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.chat.turnstile import TurnstileUnavailable
from app.config import Settings
from app.db.session import get_db_session
from app.main import create_app
from fastapi.testclient import TestClient
from pydantic import SecretStr


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        Settings(
            _env_file=None,
            rollout_percent=100,
            session_pepper=SecretStr("local-test-pepper"),
        )
    )

    async def session_override() -> AsyncGenerator[None, None]:
        yield None

    app.dependency_overrides[get_db_session] = session_override
    with TestClient(app) as test_client:
        yield test_client


def test_public_config_reports_rollout_state() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/api/v1/config").json()["enabled"] is False

    settings = Settings(_env_file=None, rollout_percent=100)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/config").json()["enabled"] is True


def test_session_route_creates_token_when_rollout_is_enabled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def create_record(*_: object) -> str:
        return "a" * 43

    monkeypatch.setattr("app.api.public.chat.create_session_record", create_record)

    response = client.post("/api/v1/sessions", json={})

    assert response.status_code == 200
    assert response.json()["session_token"] == "a" * 43


def test_turnstile_failure_uses_only_one_fail_open_per_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings(
            _env_file=None,
            rollout_percent=100,
            session_pepper=SecretStr("local-test-pepper"),
            turnstile_enabled=True,
            turnstile_secret=SecretStr("test-secret"),
            turnstile_fail_open_per_minute=1,
        )
    )

    async def session_override() -> AsyncGenerator[None, None]:
        yield None

    async def unavailable(*_: object, **__: object) -> bool:
        raise TurnstileUnavailable

    async def create_record(*_: object) -> str:
        return "a" * 43

    app.dependency_overrides[get_db_session] = session_override
    monkeypatch.setattr("app.api.public.chat.verify_turnstile", unavailable)
    monkeypatch.setattr("app.api.public.chat.create_session_record", create_record)

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/sessions",
            json={"turnstile_token": "test-token"},
        )
        second = client.post(
            "/api/v1/sessions",
            json={"turnstile_token": "test-token"},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "turnstile_temporarily_unavailable"


def test_chat_route_requires_session_and_masks_pii_before_streaming(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(id=UUID(int=1), ip_hash="client-hash")
    streamed_questions: list[str] = []

    async def find_record(*_: object) -> SimpleNamespace:
        return record

    async def fake_stream_chat(
        *args: object,
    ) -> AsyncGenerator[tuple[str, dict[str, object]], None]:
        streamed_questions.append(str(args[3]))
        yield "meta", {"path": "greeting"}
        yield "delta", {"t": "Hello."}
        yield "done", {"finish": "stop"}

    monkeypatch.setattr("app.api.public.chat.find_session", find_record)
    monkeypatch.setattr("app.api.public.chat.stream_chat", fake_stream_chat)

    missing_session = client.post(
        "/api/v1/chat/stream",
        json={"message": "hello"},
    )
    assert missing_session.status_code == 401

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "My email is ada@example.com",
            "session_token": "a" * 43,
        },
    )

    assert response.status_code == 200
    assert "event: done" in response.text
    assert "ada@example.com" not in streamed_questions[0]
    assert client.app.state.active_sessions == set()


def test_feedback_and_client_events_are_bound_to_the_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(id=UUID(int=7), ip_hash="client-hash")
    trace = SimpleNamespace(session_id=record.id, feedback=None)
    persisted_spans: list[object] = []

    class FakeSession:
        async def get(self, _: object, __: UUID) -> SimpleNamespace:
            return trace

        def add(self, span: object) -> None:
            persisted_spans.append(span)

        async def commit(self) -> None:
            return None

    fake_session = FakeSession()

    async def session_override() -> AsyncGenerator[object, None]:
        yield fake_session

    async def find_record(*_: object) -> SimpleNamespace:
        return record

    client.app.dependency_overrides[get_db_session] = session_override
    monkeypatch.setattr("app.api.public.chat.find_session", find_record)

    feedback = client.post(
        "/api/v1/feedback",
        json={"trace_id": str(UUID(int=9)), "session_token": "a" * 43, "rating": 1},
    )
    event = client.post(
        "/api/v1/client-events",
        json={
            "trace_id": str(UUID(int=9)),
            "session_token": "a" * 43,
            "event": "feedback_submitted",
        },
    )

    assert feedback.status_code == 200
    assert trace.feedback == "1"
    assert event.status_code == 200
    assert len(persisted_spans) == 1
