"""Dependências de sessão e autorização por papel do portal.

Nenhuma rota deste conjunto aceita o HMAC do Gateway, e nenhuma rota interna do
Gateway aceita cookie de sessão. Os dois esquemas não se cruzam.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.core.config import Settings
from crm_api.core.database import get_session
from crm_api.models.user import UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.users import SessionRepository, UserRepository
from crm_api.services.auth import AuthService


@dataclass(frozen=True)
class CurrentUser:
    session_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    full_name: str
    email: str
    role: UserRole


def build_auth_service(request: Request, session: AsyncSession) -> AuthService:
    settings: Settings = request.app.state.settings
    return AuthService(
        users=UserRepository(session),
        sessions=SessionRepository(session),
        audit=AuditRepository(session),
        settings=settings,
    )


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
    )


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentUser:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise _unauthenticated()

    service = build_auth_service(request, session)
    resolved = await service.resolve(token)
    # `resolve` pode revogar a sessão ou renovar a janela deslizante; ambos
    # precisam ser persistidos mesmo quando a requisição termina em 401.
    await session.commit()
    if resolved is None:
        raise _unauthenticated()

    user_session, user = resolved
    return CurrentUser(
        session_id=user_session.id,
        user_id=user.id,
        tenant_id=user.tenant_id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
    )


def require_roles(
    *roles: UserRole,
) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    """Exige um dos papéis informados.

    O escopo de carteira do representante é responsabilidade do repositório
    (R1); esta dependência decide apenas o acesso à operação, não às linhas.
    """
    allowed = frozenset(roles)

    async def dependency(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient role",
            )
        return current_user

    return dependency
