from __future__ import annotations

from types import SimpleNamespace

from app.chat.runtime import get_providers
from app.config import Settings
from pydantic import SecretStr


def test_provider_clients_are_created_once_when_configured(monkeypatch) -> None:
    created: list[str] = []

    class FakeProvider:
        def __init__(self, _: str) -> None:
            created.append(type(self).__name__)

    monkeypatch.setattr("app.chat.runtime.GroqProvider", FakeProvider)
    monkeypatch.setattr("app.chat.runtime.GeminiProvider", FakeProvider)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(
                    _env_file=None,
                    groq_api_key=SecretStr("groq-secret"),
                    google_ai_api_key=SecretStr("gemini-secret"),
                ),
                chat_providers=None,
            )
        )
    )

    providers = get_providers(request)

    assert set(providers) == {"groq", "gemini"}
    assert get_providers(request) is providers
    assert len(created) == 2
