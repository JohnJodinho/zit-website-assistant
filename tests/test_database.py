import pytest
from app.db.session import build_async_url, build_connect_args
from sqlalchemy.engine import make_url


def test_shared_transaction_pooler_disables_asyncpg_statement_cache() -> None:
    url = build_async_url(
        "postgresql://test:test@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    )
    connect_args = build_connect_args(url)

    assert connect_args["statement_cache_size"] == 0
    assert connect_args["ssl"] == "require"


def test_direct_connection_does_not_disable_statement_cache() -> None:
    url = build_async_url("postgresql://test:test@db.example.test:6543/postgres")

    assert "statement_cache_size" not in build_connect_args(url)


def test_remote_connection_can_use_supabase_root_certificate(monkeypatch, tmp_path) -> None:
    root_cert = tmp_path / "supabase-root.crt"
    url = build_async_url("postgresql://test:test@db.example.test:5432/postgres")
    monkeypatch.setattr("app.db.session.ssl.create_default_context", lambda *, cafile: cafile)

    connect_args = build_connect_args(url, root_cert)

    assert connect_args["ssl"] == str(root_cert)


def test_remote_connection_honors_explicit_sslmode_require() -> None:
    url = make_url("postgresql://test:test@db.example.test:5432/postgres?sslmode=require")

    assert build_connect_args(url)["ssl"] == "require"


def test_remote_connection_rejects_disabled_ssl() -> None:
    url = make_url("postgresql://test:test@db.example.test:5432/postgres?sslmode=disable")

    with pytest.raises(ValueError, match="require sslmode"):
        build_connect_args(url)


def test_asyncpg_url_scheme_is_preserved() -> None:
    url = build_async_url("postgresql+asyncpg://test:test@localhost:5432/postgres")

    assert url.drivername == "postgresql+asyncpg"


def test_local_connection_does_not_enable_ssl() -> None:
    url = build_async_url("postgresql://test:test@localhost:5432/postgres")

    assert build_connect_args(url) == {}


def test_sslmode_query_is_removed_for_asyncpg() -> None:
    url = build_async_url("postgresql://test:test@db.example.test:5432/postgres?sslmode=require")

    assert url.drivername == "postgresql+asyncpg"
    assert "sslmode" not in url.query
