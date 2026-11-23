from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.admin.content_routes import router as content_router
from app.api.admin.docs import register_admin_docs
from app.api.admin.etl_routes import router as etl_router
from app.api.admin.faq_routes import router as faq_router
from app.api.admin.link_routes import router as link_router
from app.api.admin.release_routes import router as release_router
from app.api.admin.routes import router as admin_router
from app.api.errors import (
    handle_http_error,
    handle_unexpected_error,
    handle_validation_error,
)
from app.api.middleware import request_context_middleware
from app.api.public.health import router as health_router
from app.config import Settings, get_settings
from app.content.snapshot import load_active_snapshot
from app.db.session import create_database_engine, create_session_factory
from app.db.models import IngestionRun
from app.obs.instrumentation import instrument_application
from app.obs.logging import configure_logging, get_logger
from app.obs.sentry import initialize_sentry
from app.obs.writer import TelemetryWriter


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
        try:
            yield
        finally:
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
    application.state.active_snapshot = None
    application.state.snapshot_error = None
    application.middleware("http")(request_context_middleware(app_settings))
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.allowed_widget_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    application.add_exception_handler(StarletteHTTPException, handle_http_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    application.add_exception_handler(Exception, handle_unexpected_error)
    application.include_router(health_router)
    application.include_router(admin_router)
    application.include_router(content_router)
    application.include_router(etl_router)
    application.include_router(faq_router)
    application.include_router(link_router)
    application.include_router(release_router)
    register_admin_docs(application, app_settings)
    instrument_application(application, engine, app_settings)
    return application


app = create_app()
