from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, cast

import httpx

from app.config import Settings

BGE_MODEL_ALIAS = "bge-base-768-v1"
BGE_MODEL_ID = "BAAI/bge-base-en-v1.5"
BGE_DIMENSIONS = 768
InputType = Literal["query", "document"]
SleepFunction = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    alias: str
    model_id: str
    revision: str
    dimensions: int
    max_input_texts: int
    max_chars_per_text: int
    max_tokens_per_text: int


class EmbeddingServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BgeEmbeddingClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: SleepFunction = asyncio.sleep,
        max_attempts: int = 3,
    ) -> None:
        if settings.zit_api_key is None:
            raise ValueError("ZIT_API_KEY is required for embedding requests")
        if settings.embedding_model != BGE_MODEL_ALIAS or settings.embedding_dimensions != 768:
            raise ValueError("Embedding settings must select bge-base-768-v1 with 768 dimensions")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")

        self._base_url = settings.embedding_api_base_url.rstrip("/")
        self._api_key = settings.zit_api_key.get_secret_value()
        self._timeout = httpx.Timeout(settings.embedding_timeout_seconds, connect=5)
        self._client = client or httpx.AsyncClient(timeout=self._timeout)
        self._owns_client = client is None
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._metadata: ModelMetadata | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def discover_model(self) -> ModelMetadata:
        if self._metadata is not None:
            return self._metadata
        readiness = await self._request("GET", "/health/ready", authenticated=False)
        if readiness.status_code != 200:
            raise EmbeddingServiceError(
                "Embedding service is not ready",
                status_code=readiness.status_code,
            )

        response = await self._request("GET", "/v1/models")
        payload = _response_json(response)
        entries = payload.get("data")
        if not isinstance(entries, list):
            raise EmbeddingServiceError("Model discovery returned an invalid response")
        model = next(
            (
                entry
                for entry in entries
                if isinstance(entry, dict) and entry.get("alias") == BGE_MODEL_ALIAS
            ),
            None,
        )
        if model is None:
            raise EmbeddingServiceError("The configured BGE model is not available")

        metadata = _parse_model_metadata(model)
        if metadata.model_id != BGE_MODEL_ID or metadata.dimensions != BGE_DIMENSIONS:
            raise EmbeddingServiceError("BGE model metadata does not match the selected model")
        self._metadata = metadata
        return metadata

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        input_type: InputType,
    ) -> list[list[float]]:
        if not texts:
            raise ValueError("texts must not be empty")
        if input_type not in {"query", "document"}:
            raise ValueError("BGE input_type must be query or document")
        if self._metadata is None:
            await self.discover_model()
        metadata = cast(ModelMetadata, self._metadata)
        _validate_texts(texts, metadata.max_chars_per_text)

        vectors: list[list[float]] = []
        for start in range(0, len(texts), metadata.max_input_texts):
            batch = texts[start : start + metadata.max_input_texts]
            vectors.extend(await self._embed_batch(batch, input_type, metadata))
        return vectors

    async def _embed_batch(
        self,
        texts: Sequence[str],
        input_type: InputType,
        metadata: ModelMetadata,
    ) -> list[list[float]]:
        response = await self._request(
            "POST",
            "/v1/embeddings",
            json={
                "model": BGE_MODEL_ALIAS,
                "input": list(texts),
                "input_type": input_type,
                "normalize_embeddings": True,
            },
        )
        payload = _response_json(response)
        return _parse_embedding_response(payload, metadata, len(texts))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}"} if authenticated else {}
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    json=json,
                )
            except httpx.TransportError as exc:
                if attempt + 1 == self._max_attempts:
                    raise EmbeddingServiceError(
                        f"Embedding service connection failed ({type(exc).__name__})"
                    ) from exc
                await self._sleep(_backoff_seconds(attempt))
                continue

            if response.status_code in {429, 503, 504} and attempt + 1 < self._max_attempts:
                await self._sleep(_retry_after_seconds(response, attempt))
                continue
            if response.is_error:
                error_code = _service_error_code(response)
                request_id = response.headers.get("x-request-id")
                request_suffix = f", request_id={request_id}" if request_id else ""
                raise EmbeddingServiceError(
                    f"Embedding service returned HTTP {response.status_code} "
                    f"({error_code}{request_suffix})",
                    status_code=response.status_code,
                )
            return response
        raise EmbeddingServiceError("Embedding service request exhausted retries")


def _validate_texts(texts: Sequence[str], max_chars: int) -> None:
    for text in texts:
        if not text or not text.strip():
            raise ValueError("Embedding inputs must not be blank")
        if len(text) > max_chars:
            raise ValueError(f"Embedding input exceeds the service limit of {max_chars} characters")


def _parse_model_metadata(value: dict[str, object]) -> ModelMetadata:
    try:
        return ModelMetadata(
            alias=_string_value(value, "alias"),
            model_id=_string_value(value, "model_id"),
            revision=_string_value(value, "revision"),
            dimensions=_int_value(value, "dimensions"),
            max_input_texts=_int_value(value, "max_input_texts"),
            max_chars_per_text=_int_value(value, "max_chars_per_text"),
            max_tokens_per_text=_int_value(value, "max_tokens_per_text"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EmbeddingServiceError("Model discovery returned invalid BGE metadata") from exc


def _parse_embedding_response(
    payload: dict[str, object],
    metadata: ModelMetadata,
    expected_count: int,
) -> list[list[float]]:
    items = _validated_embedding_items(payload, metadata, expected_count)
    return [
        _parse_embedding_vector(item, expected_index, metadata.dimensions)
        for expected_index, item in enumerate(items)
    ]


def _validated_embedding_items(
    payload: dict[str, object],
    metadata: ModelMetadata,
    expected_count: int,
) -> list[object]:
    items = payload.get("data")
    if (
        payload.get("model") != metadata.alias
        or payload.get("dimensions") != metadata.dimensions
        or not isinstance(items, list)
        or len(items) != expected_count
    ):
        raise EmbeddingServiceError("Embedding response does not match the request")
    return items


def _parse_embedding_vector(item: object, expected_index: int, dimensions: int) -> list[float]:
    raw_vector = _embedding_values(item, expected_index, dimensions)
    vector = _numeric_vector(raw_vector)
    _validate_normalized_vector(vector)
    return vector


def _embedding_values(item: object, expected_index: int, dimensions: int) -> list[object]:
    if not isinstance(item, dict) or item.get("index") != expected_index:
        raise EmbeddingServiceError("Embedding response indices are invalid")
    raw_vector = item.get("embedding")
    if not isinstance(raw_vector, list) or len(raw_vector) != dimensions:
        raise EmbeddingServiceError("Embedding vector has an unexpected dimension")
    return raw_vector


def _numeric_vector(raw_vector: list[object]) -> list[float]:
    try:
        vector = [_embedding_value(value) for value in raw_vector]
    except (OverflowError, TypeError, ValueError) as exc:
        raise EmbeddingServiceError("Embedding vector contains a non-numeric value") from exc
    if not all(math.isfinite(value) for value in vector):
        raise EmbeddingServiceError("Embedding vector contains a non-finite value")
    return vector


def _validate_normalized_vector(vector: list[float]) -> None:
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isclose(norm, 1.0, rel_tol=0.002, abs_tol=0.002):
        raise EmbeddingServiceError("Embedding vector is not normalized")


def _embedding_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Embedding vector values must be numeric")
    return float(value)


def _response_json(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise EmbeddingServiceError("Embedding service returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise EmbeddingServiceError("Embedding service returned an invalid response")
    return cast(dict[str, object], payload)


def _service_error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "request_failed"
    if not isinstance(payload, dict):
        return "request_failed"
    code = payload.get("error", payload.get("detail", "request_failed"))
    return code if isinstance(code, str) else "request_failed"


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("retry-after")
    if value is not None:
        try:
            return min(max(float(value), 0.0), 30.0)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                return min(max((retry_at - datetime.now(UTC)).total_seconds(), 0.0), 30.0)
            except (TypeError, ValueError, OverflowError):
                pass
    return _backoff_seconds(attempt)


def _backoff_seconds(attempt: int) -> float:
    jitter = float(random.uniform(0.0, 0.2))
    return float(min(0.25 * (2**attempt) + jitter, 5.0))


def _string_value(value: dict[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item:
        raise ValueError(key)
    return item


def _int_value(value: dict[str, object], key: str) -> int:
    item = value[key]
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise ValueError(key)
    return item
