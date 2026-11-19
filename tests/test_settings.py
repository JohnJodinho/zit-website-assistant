import pytest
from app.config import Settings
from pydantic import SecretStr, ValidationError


def test_development_settings_use_local_widget_origins_and_disable_sentry() -> None:
    settings = Settings(_env_file=None)

    assert settings.env == "dev"
    assert settings.allowed_widget_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    assert settings.sentry_is_enabled is False


def test_production_requires_database_and_session_pepper() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL is required in prod"):
        Settings(_env_file=None, env="prod")

    with pytest.raises(ValidationError, match="SESSION_PEPPER is required in prod"):
        Settings(
            _env_file=None,
            env="prod",
            database_url="postgresql://user:password@example.com/database",
        )


@pytest.mark.parametrize(
    "values",
    [
        {"widget_origins": "*"},
        {"widget_origins": "https://assistant.example"},
        {"widget_origins": "http://localhost:99999"},
    ],
)
def test_development_rejects_non_local_or_invalid_origins(values: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="WIDGET_ORIGINS"):
        Settings(_env_file=None, **values)


def test_admin_docs_require_both_credentials_when_enabled() -> None:
    with pytest.raises(ValidationError, match="ADMIN_DOCS_USERNAME"):
        Settings(_env_file=None, public_docs_enabled=True)

    settings = Settings(
        _env_file=None,
        public_docs_enabled=True,
        admin_docs_username=SecretStr("owner"),
        admin_docs_password=SecretStr("private"),
    )

    assert settings.public_docs_enabled is True
