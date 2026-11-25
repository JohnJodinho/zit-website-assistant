from collections.abc import Mapping
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.obs.logging import get_logger


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "trace_id", UUID(int=0)))


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = dict(headers or {})
    response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content={"error": {"code": code, "message": message, "trace_id": request_id}},
    )


async def handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return error_response(request, 500, "internal_error", "An unexpected error occurred")
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = detail if detail.replace("_", "").isalnum() else "request_error"
    return error_response(request, exc.status_code, code, detail, headers=exc.headers)


async def handle_validation_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return error_response(request, 422, "validation_error", "Request validation failed")


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    get_logger("api.errors").error(
        "unhandled_request_error",
        trace_id=_request_id(request),
        error_type=type(exc).__name__,
    )
    return error_response(request, 500, "internal_error", "An unexpected error occurred")
