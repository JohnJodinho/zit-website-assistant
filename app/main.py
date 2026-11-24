from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.admin.content_routes import router as content_router
from app.api.admin.debug_routes import router as debug_router
from app.api.admin.docs import register_admin_docs
from app.api.admin.etl_routes import router as etl_router
from app.api.admin.faq_routes import router as faq_router
from app.api.admin.link_routes import router as link_router
from app.api.admin.ops_routes import router as ops_router
from app.api.admin.release_routes import router as release_router
from app.api.admin.routes import router as admin_router
from app.api.errors import (
    handle_http_error,
    handle_unexpected_error,
    handle_validation_error,
)
from app.api.middleware import request_context_middleware
from app.api.public.chat import router as chat_router
from app.api.public.health import router as health_router
from app.chat.cache import AnswerCache
from app.chat.limits import SlidingWindowLimiter
from app.chat.quota import QuotaManager, QuotaRecord
from app.config import Settings, get_settings
from app.content.snapshot import load_active_snapshot
from app.db.models import IngestionRun, LLMCall
from app.db.session import create_database_engine, create_session_factory
from app.obs.instrumentation import instrument_application
from app.obs.logging import configure_logging, get_logger
from app.obs.sentry import initialize_sentry
from app.obs.writer import TelemetryWriter
from app.ops import run_nightly_retention


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings)
    initialize_sentry(app_settings)
    engine = create_database_engine(app_settings)
    session_factory = create_session_factory(engine) if engine is not None else None
    writer = (
        TelemetryWriter(
            session_factory=session_factory,
            max_items=app_settings.writer_queue_max,
            batch_size=app_settings.writer_batch_rows,
            flush_seconds=app_settings.writer_flush_seconds,
        )
        if session_factory is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        retention_task: asyncio.Task[None] | None = None
        if session_factory is not None:
            try:
                async with session_factory() as session:
                    await session.execute(
                        update(IngestionRun)
                        .where(IngestionRun.status == "running")
                        .values(status="interrupted")
                    )
                    await session.commit()
                    application.state.active_snapshot = await load_active_snapshot(
                        session,
                        app_settings,
                    )
                    try:
                        quota_rows = await session.scalars(
                            select(LLMCall)
                            .where(LLMCall.started_at >= datetime.now(UTC) - timedelta(days=1))
                            .order_by(LLMCall.started_at)
                            .limit(10_000)
                        )
                        application.state.quota_manager.rebuild(
                            (
                                QuotaRecord(
                                    model_id=row.model,
                                    started_at=row.started_at,
                                    status=row.status,
                                    tokens_in=row.tokens_in,
                                    tokens_out=row.tokens_out,
                                    estimated_input_tokens=row.est_tokens_in,
                                    reserved_output_tokens=row.reserved_out,
                                )
                                for row in quota_rows
                            ),
                            breaker_failures=app_settings.breaker_failures,
                            breaker_open_seconds=app_settings.breaker_min_open_s,
                        )
                    except SQLAlchemyError as exc:
                        await session.rollback()
                        get_logger("chat.quota", app_settings).warning(
                            "quota_history_restore_failed",
                            error_type=type(exc).__name__,
                        )
            except ValueError as exc:
                application.state.snapshot_error = "release_validation_failed"
                get_logger("content.snapshot", app_settings).error(
                    "active_release_validation_failed",
                    error_type=type(exc).__name__,
                )
            except SQLAlchemyError as exc:
                application.state.snapshot_error = "database_unavailable"
                get_logger("content.snapshot", app_settings).warning(
                    "active_release_load_failed",
                    error_type=type(exc).__name__,
                )
        if writer is not None:
            writer.start()
        if session_factory is not None:
            retention_task = asyncio.create_task(
                run_nightly_retention(session_factory),
                name="nightly-retention",
            )
        try:
            yield
        finally:
            if retention_task is not None:
                retention_task.cancel()
                with suppress(asyncio.CancelledError):
                    await retention_task
            providers = getattr(application.state, "chat_providers", None) or {}
            for provider in providers.values():
                close = getattr(provider, "close", None)
                if close is not None:
                    await close()
            embedding_client = getattr(application.state, "embedding_client", None)
            if embedding_client is not None:
                await embedding_client.close()
            if writer is not None:
                await writer.close(timeout=10)
            if engine is not None:
                await engine.dispose()

    application = FastAPI(
        title="ZIT Website Assistant API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.telemetry_writer = writer
    application.state.embedding_client = None
    application.state.chat_providers = None
    application.state.quota_manager = QuotaManager()
    application.state.answer_cache = AnswerCache()
    application.state.session_rate_limiter = SlidingWindowLimiter()
    application.state.chat_rate_limiter = SlidingWindowLimiter()
    application.state.turnstile_fail_open_limiter = SlidingWindowLimiter()
    application.state.active_sessions = set()
    application.state.query_embedding_cache = {}
    application.state.active_snapshot = None
    application.state.snapshot_error = None
    application.middleware("http")(request_context_middleware(app_settings))
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.allowed_widget_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    application.add_exception_handler(StarletteHTTPException, handle_http_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    application.add_exception_handler(Exception, handle_unexpected_error)
    application.include_router(health_router)
    application.include_router(chat_router)
    application.include_router(admin_router)
    application.include_router(content_router)
    application.include_router(etl_router)
    application.include_router(faq_router)
    application.include_router(link_router)
    application.include_router(release_router)
    application.include_router(debug_router)
    application.include_router(ops_router)
    register_admin_docs(application, app_settings)
    instrument_application(application, engine, app_settings)
    return application


app = create_app()
