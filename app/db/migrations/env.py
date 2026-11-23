from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

import app.db.models  # noqa: F401
from app.config import get_settings
from app.db.base import Base
from app.db.session import build_async_url, build_connect_args

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def migration_url() -> URL:
    settings = get_settings()
    secret_url = settings.database_url_direct or settings.database_url
    if secret_url is None:
        raise ValueError("DATABASE_URL_DIRECT or DATABASE_URL is required for migrations")
    return build_async_url(secret_url.get_secret_value())


def include_name(
    name: str | None,
    type_: Literal[
        "schema",
        "table",
        "column",
        "index",
        "unique_constraint",
        "foreign_key_constraint",
        "check_constraint",
    ],
    parent_names: MutableMapping[
        Literal["schema_name", "table_name", "schema_qualified_table_name"],
        str | None,
    ],
) -> bool:
    return type_ != "schema" or name == "assistant"


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    settings = get_settings()
    raw_url = settings.database_url_direct or settings.database_url
    if raw_url is None:
        raise ValueError("DATABASE_URL_DIRECT or DATABASE_URL is required for migrations")
    url = migration_url()
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
        connect_args=build_connect_args(
            make_url(raw_url.get_secret_value()),
            settings.database_ssl_root_cert,
        ),
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
