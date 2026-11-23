from __future__ import annotations

import re

_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "phone": re.compile(r"(?<!\d)(?:\+234|234|0)?(?:[789][01]\d{8}|[789][01]\d{7})(?!\d)"),
    "nin_bvn": re.compile(r"(?<!\d)\d{11}(?!\d)"),
    "dob": re.compile(r"\b(?:\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})\b"),
    "name": re.compile(r"\b(?:my name is|I am)\s+[A-Z][A-Za-z'-]+", re.I),
    "address": re.compile(
        r"\b(?:street|road|avenue|close|crescent|plot)\b.{0,40}",
        re.I,
    ),
}


def mask_pii(text: str) -> tuple[str, list[str]]:
    masked = text
    found: list[str] = []
    for kind, pattern in _PATTERNS.items():
        masked, count = pattern.subn(f"[{kind.upper()}]", masked)
        if count:
            found.append(kind)
    return masked, found
