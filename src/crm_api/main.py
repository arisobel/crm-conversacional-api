import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from crm_api.api.router import api_router
from crm_api.core.config import Settings, get_settings
from crm_api.core.database import create_session_factory
from crm_api.core.rate_limit import SlidingWindowRateLimiter
from crm_api.web.dependencies import STATIC_DIR, PortalRedirect
from crm_api.web.routes import router as portal_router


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

    app = FastAPI(
        title="CRM Conversacional API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if app_settings.expose_api_docs else None,
        redoc_url="/redoc" if app_settings.expose_api_docs else None,
        openapi_url="/openapi.json" if app_settings.expose_api_docs else None,
    )
    app.state.settings = app_settings
    app.state.engine, app.state.session_factory = create_session_factory(app_settings)
    app.state.login_rate_limiter = SlidingWindowRateLimiter(
        max_attempts=app_settings.login_rate_limit_attempts,
        window_seconds=app_settings.login_rate_limit_window_seconds,
    )
    app.logger = logging.getLogger("crm_api")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Cabeçalhos que valem para toda resposta, inclusive as de erro.

        `frame-ancestors 'none'` é o que barra o clickjacking em navegador atual;
        `X-Frame-Options` fica junto para os que ainda não leem CSP. O portal não
        carrega script nem estilo de fora, então a política pode ser restritiva
        sem quebrar nada.
        """
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; form-action 'self'; "
            "base-uri 'none'; object-src 'none'",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

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

    @app.exception_handler(PortalRedirect)
    async def portal_redirect_handler(_: Request, error: PortalRedirect) -> RedirectResponse:
        # As páginas do portal devolvem HTML: uma sessão ausente precisa levar
        # ao login, e não a um problem+json que o navegador exibiria cru.
        response = RedirectResponse(error.location, status_code=303)
        if error.clear_session:
            response.delete_cookie(key=app_settings.session_cookie_name, path="/")
        return response

    app.include_router(api_router)
    app.include_router(portal_router)
    app.mount(
        "/portal/static", StaticFiles(directory=str(STATIC_DIR)), name="portal-static"
    )
    return app


app = create_app()
