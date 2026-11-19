from urllib.parse import urlsplit, urlunsplit

import sentry_sdk
from sentry_sdk.types import Event, Hint

from app.config import Settings


def _remove_sensitive_request_data(event: Event, hint: Hint) -> Event | None:
    request = event.get("request")
    if isinstance(request, dict):
        for field in ("data", "cookies", "headers", "query_string"):
            request.pop(field, None)
        url = request.get("url")
        if isinstance(url, str):
            parts = urlsplit(url)
            request["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    event.pop("user", None)
    return event


def initialize_sentry(settings: Settings) -> bool:
    if not settings.sentry_is_enabled:
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.env,
        release=settings.git_sha,
        send_default_pii=False,
        traces_sample_rate=0.0,
        max_request_body_size="never",
        before_send=_remove_sensitive_request_data,
    )
    return True
