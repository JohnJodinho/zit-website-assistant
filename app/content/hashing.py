from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def hash_content(
    text: str,
    embed_text: str | None,
    metadata: Mapping[str, Any],
) -> str:
    payload = json.dumps(
        {"text": text, "embed_text": embed_text, "metadata": metadata},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
