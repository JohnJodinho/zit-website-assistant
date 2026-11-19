from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings

_provider_configured = False
_httpx_instrumented = False
_sqlalchemy_instrumented = False


def instrument_application(
    application: FastAPI,
    engine: AsyncEngine | None,
    settings: Settings,
) -> None:
    global _provider_configured, _httpx_instrumented, _sqlalchemy_instrumented
    if not _provider_configured:
        trace.set_tracer_provider(
            TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": "zit-website-assistant",
                        "deployment.environment": settings.env,
                        "service.version": settings.git_sha,
                    }
                )
            )
        )
        _provider_configured = True

    FastAPIInstrumentor.instrument_app(application)
    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True
    if engine is not None and not _sqlalchemy_instrumented:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        _sqlalchemy_instrumented = True
