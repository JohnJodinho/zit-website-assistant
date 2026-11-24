from __future__ import annotations

import re
from collections.abc import Sequence

from app.content.snapshot import SnapshotLink
from app.search.hybrid import SearchHit

_URL = re.compile(r"https?://[^\s)>\]]+", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+?234|0)(?:[\s().-]*\d){10,13}(?!\w)")


def answer_is_grounded(
    answer: str,
    hits: Sequence[SearchHit],
    links: Sequence[SnapshotLink],
) -> bool:
    context = "\n".join(hit.text for hit in hits)
    allowed_urls = {link.url.rstrip(".,;:") for link in links}
    if any(url.rstrip(".,;:") not in allowed_urls for url in _URL.findall(answer)):
        return False
    allowed_phones = {_digits(value) for value in _PHONE.findall(context)}
    return all(_digits(value) in allowed_phones for value in _PHONE.findall(answer))


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())
