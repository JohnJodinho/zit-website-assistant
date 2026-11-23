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
    database_url_session: SecretStr | None = None
    database_url_direct: SecretStr | None = None
    database_ssl_root_cert: Path | None = None
    zit_api_key: SecretStr | None = None
    embedding_api_base_url: str = "https://johnalbarkaibrahim-sentimentscope.hf.space"
    embedding_model: Literal["bge-base-768-v1"] = "bge-base-768-v1"
    embedding_dimensions: int = 768
    embedding_timeout_seconds: float = 100.0
    db_pool_size: int = 8
    writer_queue_max: int = 5000
    writer_batch_rows: int = 100
    writer_flush_seconds: float = 1.0
    etl_max_json_mb: int = 5
    etl_max_zip_mb: int = 20
    etl_max_zip_files: int = 500
    etl_max_removal_percent: int = 15
    etl_max_count_swing_percent: int = 50
    etl_missing_section_fail_percent: int = 10
    chunk_hard_max_tokens: int = 350
    gate_vector_min: float = 0.62
    gate_bm25_min: float = 0.30
    gate_bm25_min_degraded: float = 0.45
    gate_retrieval_min_hit: float = 0.95
    gate_max_drop_points: float = 0.02
    faq_direct_sim: float = 0.90
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
    google_ai_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    llm_models: str = "[]"
    quota_safety_per_minute: float = 0.90
    quota_safety_daily: float = 0.95
    llm_pretoken_deadline_s: float = 12.0
    llm_first_token_timeout_s: float = 8.0
    llm_max_attempts: int = 3
    breaker_failures: int = 3
    breaker_min_open_s: float = 30.0
    sse_ping_seconds: float = 15.0
    message_max_chars: int = 500
    session_ttl_minutes: int = 30
    session_max_hours: int = 4
    session_cache_seconds: int = 300
    turnstile_enabled: bool = False
    turnstile_secret: SecretStr | None = None
    rollout_percent: int = 0
    kill_switch: bool = False
    maintenance_message: str = "ZIT assistant is temporarily unavailable."
    fast_greeting: bool = True
    fast_contact: bool = True
    fast_apply: bool = True
    fast_field: bool = True
    fast_category: bool = True
    fast_faq: bool = True

    @model_validator(mode="after")
    def validate_settings(self) -> Settings:
        self._validate_production_settings()
        self._validate_resource_settings()
        self._validate_admin_docs_settings()
        self._validate_embedding_settings()
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
        if min(self.etl_max_json_mb, self.etl_max_zip_mb, self.etl_max_zip_files) < 1:
            raise ValueError("ETL upload limits must be positive")
        if any(
            not 0 <= value <= 100
            for value in (
                self.etl_max_removal_percent,
                self.etl_max_count_swing_percent,
                self.etl_missing_section_fail_percent,
            )
        ):
            raise ValueError("ETL percentage limits must be between 0 and 100")
        if self.chunk_hard_max_tokens < 1:
            raise ValueError("CHUNK_HARD_MAX_TOKENS must be positive")
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

    def _validate_embedding_settings(self) -> None:
        parts = urlsplit(self.embedding_api_base_url)
        if self.embedding_dimensions != 768:
            raise ValueError("EMBEDDING_DIMENSIONS must be 768")
        dev_local_http = (
            self.env == "dev" and parts.scheme == "http" and self._is_local_origin(parts.hostname)
        )
        if parts.scheme != "https" and not dev_local_http:
            raise ValueError("EMBEDDING_API_BASE_URL must use HTTPS")
        if not parts.netloc or parts.username or parts.password:
            raise ValueError("EMBEDDING_API_BASE_URL must be an origin without credentials")
        if parts.path not in {"", "/"} or parts.query or parts.fragment:
            raise ValueError("EMBEDDING_API_BASE_URL must not include a path or query")
        if self.embedding_timeout_seconds <= 0:
            raise ValueError("EMBEDDING_TIMEOUT_SECONDS must be positive")

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
