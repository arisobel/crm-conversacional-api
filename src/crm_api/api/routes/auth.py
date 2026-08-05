from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, build_auth_service, get_current_user
from crm_api.core.config import Settings
from crm_api.core.database import get_session
from crm_api.schemas.auth import AuthenticatedUserResponse, LoginRequest
from crm_api.services.auth import AuthenticationFailed, normalize_email

router = APIRouter(prefix="/admin/auth", tags=["Portal Authentication"])

_INVALID_CREDENTIALS = "invalid credentials"


def _client_key(request: Request, email: str) -> str:
    """Chave do limitador.

    Usa o IP da conexão, não `X-Forwarded-For`: sem uma lista de proxies
    confiáveis, aceitar o cabeçalho permitiria burlar o limite forjando um IP a
    cada tentativa. Atrás de proxy reverso, isso agrupa por proxy — o bloqueio
    por conta em `users.locked_until` é o controle que continua valendo.
    """
    host = request.client.host if request.client else "unknown"
    return f"{host}|{email}"


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_absolute_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


@router.post(
    "/login",
    response_model=AuthenticatedUserResponse,
    responses={
        401: {"description": "Invalid credentials"},
        429: {"description": "Too many attempts"},
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthenticatedUserResponse:
    settings: Settings = request.app.state.settings
    email = normalize_email(payload.email)

    if not request.app.state.login_rate_limiter.allow(_client_key(request, email)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many login attempts",
        )

    service = build_auth_service(request, session)
    try:
        issued = await service.authenticate(
            tenant_slug=settings.tenant_slug,
            email=email,
            password=payload.password.get_secret_value(),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthenticationFailed as error:
        # A auditoria da tentativa e a contagem de falhas precisam sobreviver à
        # resposta de erro.
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS,
        ) from error

    await session.commit()
    _set_session_cookie(response, settings, issued.token)
    return AuthenticatedUserResponse(
        user_id=issued.user.id,
        tenant_id=issued.user.tenant_id,
        full_name=issued.user.full_name,
        email=issued.user.email,
        role=issued.user.role,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"description": "Unauthorized"}},
)
async def logout(
    request: Request,
    response: Response,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    settings: Settings = request.app.state.settings
    service = build_auth_service(request, session)
    await service.logout(
        session_id=current_user.session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
    )
    await session.commit()
    response.delete_cookie(key=settings.session_cookie_name, path="/")


@router.get(
    "/me",
    response_model=AuthenticatedUserResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(
        user_id=current_user.user_id,
        tenant_id=current_user.tenant_id,
        full_name=current_user.full_name,
        email=current_user.email,
        role=current_user.role,
    )
