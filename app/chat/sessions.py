from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta


def create_session_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def hash_session_token(token: str, pepper: str) -> str:
    return hmac.new(
        pepper.encode("utf-8"),
        token.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def session_expiry(minutes: int, max_hours: int) -> datetime:
    now = datetime.now(UTC)
    return min(now + timedelta(minutes=minutes), now + timedelta(hours=max_hours))
