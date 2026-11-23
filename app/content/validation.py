from __future__ import annotations

import math
import re
from typing import Any

from app.content.hashing import hash_content
from app.content.models import ContentChunk

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_URL = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_CHUNK_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_./-]*(?:#[A-Za-z0-9][A-Za-z0-9:_./-]*)?$")


class ContentValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def build_manual_chunk(
    chunk_key: str,
    doc_key: str,
    kind: str,
    text: str,
    embed_text: str | None,
    metadata: dict[str, Any],
    max_tokens: int,
) -> ContentChunk:
    if not _CHUNK_KEY.fullmatch(chunk_key):
        raise ContentValidationError("invalid_chunk_key")
    normalized_text = text.strip()
    normalized_embed_text = embed_text.strip() if embed_text is not None else None
    if not normalized_text:
        raise ContentValidationError("chunk_text_cannot_be_blank")
    token_count = math.ceil(len(normalized_text) / 3.5)
    if token_count < 20 or token_count > max_tokens:
        raise ContentValidationError("invalid_chunk_length")
    if (
        _URL.search(normalized_text)
        or _EMAIL.search(normalized_text)
        or re.search(r"(?m)^\s*#{1,6}\s", normalized_text)
        or (
            normalized_embed_text is not None
            and (_URL.search(normalized_embed_text) or _EMAIL.search(normalized_embed_text))
        )
    ):
        raise ContentValidationError("chunk_text_contains_disallowed_content")
    return ContentChunk(
        chunk_key=chunk_key,
        doc_key=doc_key,
        kind=kind.strip(),
        text=normalized_text,
        token_count=token_count,
        content_hash=hash_content(normalized_text, normalized_embed_text, metadata),
        metadata=metadata,
        embed_text=normalized_embed_text,
    )
