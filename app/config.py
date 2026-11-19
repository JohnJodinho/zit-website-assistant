from __future__ import annotations

from ipaddress import ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["dev", "staging", "prod"] = "dev"
    database_url: SecretStr | None = None
    database_url_direct: SecretStr | None = None
    database_ssl_root_cert: Path | None = None
    db_pool_size: int = 8
    writer_queue_max: int = 5000
    writer_batch_rows: int = 100
    writer_flush_seconds: float = 1.0
    session_pepper: SecretStr | None = None
    admin_bootstrap_key_hash: SecretStr | None = None
    admin_docs_username: SecretStr | None = None
    admin_docs_password: SecretStr | None = None
    public_docs_enabled: bool = False
    widget_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    admin_ip_allowlist: str = ""
    trusted_proxy_hops: int = 0
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    git_sha: str = "local"
    sentry_dsn: SecretStr = SecretStr("placeholder")
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def validate_settings(self) -> Settings:
        self._validate_production_settings()
        self._validate_resource_settings()
        self._validate_admin_docs_settings()
        self._validate_origins()
        self._validate_ip_allowlist()
        return self

    def _validate_production_settings(self) -> None:
        if self.env != "prod":
            return
        if self.database_url is None:
            raise ValueError("DATABASE_URL is required in prod")
        if not self._has_value(self.session_pepper):
            raise ValueError("SESSION_PEPPER is required in prod")

    def _validate_resource_settings(self) -> None:
        if self.db_pool_size < 1:
            raise ValueError("DB_POOL_SIZE must be at least 1")
        if self.writer_queue_max < 1 or self.writer_batch_rows < 1:
            raise ValueError("WRITER_QUEUE_MAX and WRITER_BATCH_ROWS must be positive")
        if self.writer_flush_seconds <= 0:
            raise ValueError("WRITER_FLUSH_SECONDS must be positive")
        if self.trusted_proxy_hops < 0:
            raise ValueError("TRUSTED_PROXY_HOPS cannot be negative")

    def _validate_admin_docs_settings(self) -> None:
        docs_username_set = self._has_value(self.admin_docs_username)
        docs_password_set = self._has_value(self.admin_docs_password)
        if docs_username_set != docs_password_set:
            raise ValueError("ADMIN_DOCS_USERNAME and ADMIN_DOCS_PASSWORD must both be set")
        if self.public_docs_enabled and not docs_username_set:
            raise ValueError(
                "ADMIN_DOCS_USERNAME and ADMIN_DOCS_PASSWORD are required when "
                "PUBLIC_DOCS_ENABLED is true"
            )

    @property
    def allowed_widget_origins(self) -> tuple[str, ...]:
        return tuple(origin.strip() for origin in self.widget_origins.split(",") if origin.strip())

    @property
    def allowed_admin_networks(self) -> tuple[str, ...]:
        return tuple(
            network.strip() for network in self.admin_ip_allowlist.split(",") if network.strip()
        )

    @property
    def sentry_is_enabled(self) -> bool:
        value = self.sentry_dsn.get_secret_value().strip()
        return bool(value) and value.lower() != "placeholder"

    @staticmethod
    def _has_value(value: SecretStr | None) -> bool:
        return value is not None and bool(value.get_secret_value().strip())

    def _validate_origins(self) -> None:
        for origin in self.allowed_widget_origins:
            parts = self._parse_widget_origin(origin)
            self._validate_origin_port(parts)
            if self.env == "dev" and not self._is_local_origin(parts.hostname):
                raise ValueError("WIDGET_ORIGINS in dev may contain only local origins")

    @staticmethod
    def _parse_widget_origin(origin: str) -> SplitResult:
        parts = urlsplit(origin)
        if parts.scheme not in {"http", "https"}:
            raise ValueError("WIDGET_ORIGINS must contain exact HTTP(S) origins")
        if not parts.netloc:
            raise ValueError("WIDGET_ORIGINS must contain exact HTTP(S) origins")
        if parts.path or parts.query or parts.fragment:
            raise ValueError("WIDGET_ORIGINS must contain exact HTTP(S) origins")
        if "*" in origin:
            raise ValueError("WIDGET_ORIGINS must contain exact HTTP(S) origins")
        return parts

    @staticmethod
    def _validate_origin_port(parts: SplitResult) -> None:
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError("WIDGET_ORIGINS contains an invalid port") from exc
        if port is not None and not 0 < port < 65536:
            raise ValueError("WIDGET_ORIGINS contains an invalid port")

    @staticmethod
    def _is_local_origin(hostname: str | None) -> bool:
        return hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }

    def _validate_ip_allowlist(self) -> None:
        for value in self.allowed_admin_networks:
            try:
                ip_network(value, strict=False)
            except ValueError as exc:
                raise ValueError("ADMIN_IP_ALLOWLIST must contain IPs or CIDR networks") from exc


def get_settings() -> Settings:
    return Settings()
