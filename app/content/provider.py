from __future__ import annotations

from fastapi import HTTPException, Request

from app.api.deps import get_embedding_client
from app.embeddings.client import EmbeddingServiceError


async def embed_documents(request: Request, texts: list[str]) -> tuple[list[list[float]], str]:
    client = get_embedding_client(request)
    try:
        metadata = await client.discover_model()
        vectors = await client.embed_texts(texts, input_type="document")
    except EmbeddingServiceError as exc:
        raise HTTPException(status_code=503, detail="embedding_service_unavailable") from exc
    if len(vectors) != len(texts):
        raise HTTPException(status_code=503, detail="embedding_response_mismatch")
    return vectors, metadata.model_id
