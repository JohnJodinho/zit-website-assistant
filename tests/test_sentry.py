from app.config import Settings
from app.obs.sentry import _remove_sensitive_request_data, initialize_sentry
from pydantic import SecretStr


def test_placeholder_dsn_does_not_initialize_sentry(monkeypatch) -> None:
    def fail_if_initialized(**kwargs) -> None:
        raise AssertionError("Sentry must remain disabled for the placeholder DSN")

    monkeypatch.setattr("app.obs.sentry.sentry_sdk.init", fail_if_initialized)
    settings = Settings(_env_file=None, sentry_dsn=SecretStr("placeholder"))

    assert initialize_sentry(settings) is False


def test_sentry_event_filter_removes_sensitive_request_data() -> None:
    event = {
        "request": {
            "url": "https://example.test/chat?secret=value#section",
            "data": "private text",
            "cookies": {"session": "private"},
            "headers": {"authorization": "private"},
            "query_string": "secret=value",
        },
        "user": {"id": "private"},
    }

    filtered = _remove_sensitive_request_data(event, {})

    assert filtered == {"request": {"url": "https://example.test/chat"}}
