import hmac
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.responses import HTMLResponse, JSONResponse

from app.config import Settings


def register_admin_docs(application: FastAPI, settings: Settings) -> None:
    if not settings.public_docs_enabled:
        return

    basic_auth = HTTPBasic(auto_error=False)
    expected_username = settings.admin_docs_username
    expected_password = settings.admin_docs_password
    if expected_username is None or expected_password is None:
        raise ValueError("Admin docs credentials are required when docs are enabled")

    async def verify_docs_auth(
        credentials: Annotated[HTTPBasicCredentials | None, Depends(basic_auth)],
    ) -> None:
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="docs_auth_required",
                headers={"WWW-Authenticate": "Basic"},
            )
        username_matches = hmac.compare_digest(
            credentials.username, expected_username.get_secret_value()
        )
        password_matches = hmac.compare_digest(
            credentials.password, expected_password.get_secret_value()
        )
        if not (username_matches and password_matches):
            raise HTTPException(
                status_code=401,
                detail="docs_auth_required",
                headers={"WWW-Authenticate": "Basic"},
            )

    @application.get(
        "/admin/docs",
        include_in_schema=False,
        dependencies=[Depends(verify_docs_auth)],
    )
    async def admin_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/admin/openapi.json",
            title="ZIT Assistant Admin API",
        )

    @application.get(
        "/admin/openapi.json",
        include_in_schema=False,
        dependencies=[Depends(verify_docs_auth)],
    )
    async def admin_openapi() -> JSONResponse:
        return JSONResponse(application.openapi())
