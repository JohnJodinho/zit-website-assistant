from __future__ import annotations

from typing import cast

from fastapi import Request

from app.chat.providers import GeminiProvider, GroqProvider, StreamingProvider
from app.config import Settings


def get_providers(request: Request) -> dict[str, StreamingProvider]:
    existing = getattr(request.app.state, "chat_providers", None)
    if existing is not None:
        return cast(dict[str, StreamingProvider], existing)

    settings: Settings = request.app.state.settings
    providers: dict[str, StreamingProvider] = {}
    if settings.groq_api_key is not None:
        providers["groq"] = GroqProvider(settings.groq_api_key.get_secret_value())
    if settings.google_ai_api_key is not None:
        providers["gemini"] = GeminiProvider(settings.google_ai_api_key.get_secret_value())
    request.app.state.chat_providers = providers
    return providers
