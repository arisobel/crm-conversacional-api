import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from crm_api.api.router import api_router
from crm_api.core.config import Settings, get_settings
from crm_api.core.database import create_session_factory
from crm_api.core.rate_limit import SlidingWindowRateLimiter


def _problem_response(status_code: int, title: str, detail: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "about:blank", "title": title, "status": status_code, "detail": detail},
        media_type="application/problem+json",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        await application.state.engine.dispose()

    app = FastAPI(title="CRM Conversacional API", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.engine, app.state.session_factory = create_session_factory(app_settings)
    app.state.login_rate_limiter = SlidingWindowRateLimiter(
        max_attempts=app_settings.login_rate_limit_attempts,
        window_seconds=app_settings.login_rate_limit_window_seconds,
    )
    app.logger = logging.getLogger("crm_api")

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, error: HTTPException) -> JSONResponse:
        title = {
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            409: "Conflict",
            422: "Unprocessable Content",
            429: "Too Many Requests",
            503: "Service Unavailable",
        }.get(error.status_code, "Request Error")
        return _problem_response(error.status_code, title, str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        return _problem_response(422, "Unprocessable Content", "request validation failed")

    app.include_router(api_router)
    return app


app = create_app()
