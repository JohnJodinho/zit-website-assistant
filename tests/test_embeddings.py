from __future__ import annotations

import json

import httpx
import pytest
from app.config import Settings
from app.embeddings.client import (
    BGE_DIMENSIONS,
    BGE_MODEL_ALIAS,
    BGE_MODEL_ID,
    BgeEmbeddingClient,
    EmbeddingServiceError,
)
from pydantic import SecretStr


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        zit_api_key=SecretStr("test-zit-key"),
    )


def _model_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "alias": BGE_MODEL_ALIAS,
        "model_id": BGE_MODEL_ID,
        "revision": "fixed-test-revision",
        "dimensions": BGE_DIMENSIONS,
        "max_input_texts": 2,
        "max_chars_per_text": 2048,
        "max_tokens_per_text": 512,
    }
    entry.update(overrides)
    return entry


def _unit_vector() -> list[float]:
    return [1.0, *([0.0] * (BGE_DIMENSIONS - 1))]


def _response(request: httpx.Request, payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=request,
        headers={"X-Request-ID": "test-request"},
    )


async def test_client_discovers_service_limits_and_splits_batches() -> None:
    requests: list[tuple[str, dict[str, object] | None]] = []
    sleeps: list[float] = []

    async def no_wait(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return _response(request, {"ready": True})
        if request.url.path == "/v1/models":
            assert request.headers["authorization"] == "Bearer test-zit-key"
            return _response(request, {"data": [_model_entry()]})
        body = json.loads(request.content)
        requests.append((body["input_type"], body))
        return _response(
            request,
            {
                "model": BGE_MODEL_ALIAS,
                "dimensions": BGE_DIMENSIONS,
                "data": [
                    {"index": index, "embedding": _unit_vector()}
                    for index, _ in enumerate(body["input"])
                ],
                "usage": {"input_texts": len(body["input"])},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = BgeEmbeddingClient(_settings(), client=http_client, sleep=no_wait)
        vectors = await client.embed_texts(
            ["first passage", "second passage", "third passage"],
            input_type="document",
        )

    assert len(vectors) == 3
    assert all(len(vector) == BGE_DIMENSIONS for vector in vectors)
    assert [len(request[1]["input"]) for request in requests if request[1] is not None] == [2, 1]
    assert all(request[0] == "document" for request in requests)
    assert sleeps == [pytest.approx(2.1)]


async def test_client_uses_query_input_type_and_rejects_bad_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return _response(request, {"ready": True})
        if request.url.path == "/v1/models":
            return _response(request, {"data": [_model_entry()]})
        return _response(
            request,
            {
                "model": BGE_MODEL_ALIAS,
                "dimensions": BGE_DIMENSIONS,
                "data": [{"index": 0, "embedding": [0.25] * BGE_DIMENSIONS}],
                "usage": {"input_texts": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BgeEmbeddingClient(_settings(), client=http_client)
        with pytest.raises(EmbeddingServiceError, match="not normalized"):
            await client.embed_texts(["A question"], input_type="query")


async def test_client_rejects_boolean_vector_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return _response(request, {"ready": True})
        if request.url.path == "/v1/models":
            return _response(request, {"data": [_model_entry()]})
        return _response(
            request,
            {
                "model": BGE_MODEL_ALIAS,
                "dimensions": BGE_DIMENSIONS,
                "data": [{"index": 0, "embedding": [True, *([0.0] * (BGE_DIMENSIONS - 1))]}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BgeEmbeddingClient(_settings(), client=http_client)
        with pytest.raises(EmbeddingServiceError, match="non-numeric"):
            await client.embed_texts(["A public fact"], input_type="document")


async def test_client_retries_transient_service_errors_with_retry_after() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def no_wait(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/health/ready":
            return _response(request, {"ready": True})
        if request.url.path == "/v1/models":
            return _response(request, {"data": [_model_entry()]})
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503,
                json={"error": "queue_full"},
                headers={"Retry-After": "0"},
                request=request,
            )
        return _response(
            request,
            {
                "model": BGE_MODEL_ALIAS,
                "dimensions": BGE_DIMENSIONS,
                "data": [{"index": 0, "embedding": _unit_vector()}],
                "usage": {"input_texts": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BgeEmbeddingClient(_settings(), client=http_client, sleep=no_wait)
        vectors = await client.embed_texts(["A public course description"], input_type="document")

    assert len(vectors) == 1
    assert attempts == 2
    assert sleeps == [0.0, pytest.approx(2.1)]


async def test_authentication_error_does_not_expose_key_or_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/health/ready":
            return _response(request, {"ready": True})
        if request.url.path == "/v1/models":
            attempts += 1
            return httpx.Response(
                401,
                json={"detail": "invalid_auth"},
                request=request,
            )
        raise AssertionError("Embedding endpoint must not be called after auth failure")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BgeEmbeddingClient(_settings(), client=http_client, max_attempts=3)
        with pytest.raises(EmbeddingServiceError) as error:
            await client.discover_model()

    assert error.value.status_code == 401
    assert "test-zit-key" not in str(error.value)
    assert attempts == 1


def test_settings_reject_insecure_remote_embedding_url() -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        Settings(
            _env_file=None,
            embedding_api_base_url="http://example.test",
        )


def test_http_embedding_url_is_allowed_only_for_local_development() -> None:
    settings = Settings(_env_file=None, embedding_api_base_url="http://localhost:8080")
    assert settings.embedding_api_base_url == "http://localhost:8080"

    with pytest.raises(ValueError, match="must use HTTPS"):
        Settings(
            _env_file=None,
            env="prod",
            database_url=SecretStr("postgresql://db.example.test/app"),
            session_pepper=SecretStr("test-pepper"),
            embedding_api_base_url="http://localhost:8080",
        )

    with pytest.raises(ValueError, match="must use HTTPS"):
        Settings(_env_file=None, embedding_api_base_url="ftp://localhost:8080")


def test_settings_reject_non_bge_embedding_dimensions() -> None:
    with pytest.raises(ValueError, match="must be 768"):
        Settings(_env_file=None, embedding_dimensions=384)


async def test_client_rejects_an_alias_resolved_to_a_different_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return _response(request, {"ready": True})
        return _response(
            request,
            {"data": [_model_entry(model_id="another/model")]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BgeEmbeddingClient(_settings(), client=http_client)
        with pytest.raises(EmbeddingServiceError, match="does not match"):
            await client.discover_model()
