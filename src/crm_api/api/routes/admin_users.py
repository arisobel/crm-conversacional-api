import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, require_roles
from crm_api.core.database import get_session
from crm_api.core.passwords import WeakPassword
from crm_api.core.phone import InvalidWhatsappNumber
from crm_api.models.user import User, UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.users import SessionRepository, UserRepository
from crm_api.schemas.users import (
    CreateUserRequest,
    SetPasswordRequest,
    UpdateUserRequest,
    UserPage,
    UserResponse,
)
from crm_api.services.users import (
    EmailAlreadyUsed,
    UnsafeUserChange,
    UserNotFound,
    UserService,
    WhatsappAlreadyUsed,
)

router = APIRouter(prefix="/admin/users", tags=["Portal Users"])

_AdminOnly = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]


def _build_service(request: Request, session: AsyncSession) -> UserService:
    return UserService(
        users=UserRepository(session),
        sessions=SessionRepository(session),
        audit=AuditRepository(session),
        settings=request.app.state.settings,
    )


def _response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        whatsapp_e164=user.whatsapp_e164,
        active=user.active,
        last_login_at=user.last_login_at,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Insufficient role"},
        409: {"description": "Email already used"},
        422: {"description": "Weak password"},
    },
)
async def create_user(
    payload: CreateUserRequest,
    request: Request,
    current_user: _AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    service = _build_service(request, session)
    try:
        user = await service.create(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password.get_secret_value(),
            role=payload.role,
            whatsapp_e164=payload.whatsapp_e164,
            request_id=request.headers.get("x-request-id"),
        )
    except EmailAlreadyUsed as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already used"
        ) from error
    except WhatsappAlreadyUsed as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except InvalidWhatsappNumber as error:
        raise _unprocessable(str(error)) from error
    except WeakPassword as error:
        raise _unprocessable(str(error)) from error

    await session.commit()
    return _response(user)


@router.get("", response_model=UserPage, responses={403: {"description": "Insufficient role"}})
async def list_users(
    request: Request,
    current_user: _AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
    role: Annotated[UserRole | None, Query()] = None,
    active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserPage:
    rows, total = await _build_service(request, session).list_users(
        tenant_id=current_user.tenant_id,
        role=role,
        active=active,
        limit=limit,
        offset=offset,
    )
    return UserPage(
        items=[_response(user) for user in rows], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses={403: {"description": "Insufficient role"}, 404: {"description": "Not found"}},
)
async def get_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: _AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    try:
        user = await _build_service(request, session).get(
            tenant_id=current_user.tenant_id, user_id=user_id
        )
    except UserNotFound as error:
        raise _not_found() from error
    return _response(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    responses={
        403: {"description": "Insufficient role"},
        404: {"description": "Not found"},
        422: {"description": "Unsafe change"},
    },
)
async def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    request: Request,
    current_user: _AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    service = _build_service(request, session)
    try:
        user = await service.update(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            user_id=user_id,
            full_name=payload.full_name,
            whatsapp_e164=payload.whatsapp_e164,
            role=payload.role,
            request_id=request.headers.get("x-request-id"),
        )
    except UserNotFound as error:
        raise _not_found() from error
    except WhatsappAlreadyUsed as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except InvalidWhatsappNumber as error:
        raise _unprocessable(str(error)) from error
    except UnsafeUserChange as error:
        raise _unprocessable(str(error)) from error

    await session.commit()
    return _response(user)


@router.post(
    "/{user_id}/deactivate",
    response_model=UserResponse,
    responses={
        403: {"description": "Insufficient role"},
        404: {"description": "Not found"},
        422: {"description": "Unsafe change"},
    },
)
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: _AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    """Desativa a conta e revoga as sessões já emitidas."""
    return await _set_active(user_id, request, current_user, session, active=False)


@router.post(
    "/{user_id}/activate",
    response_model=UserResponse,
    responses={403: {"description": "Insufficient role"}, 404: {"description": "Not found"}},
)
async def activate_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: _AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    return await _set_active(user_id, request, current_user, session, active=True)


async def _set_active(
    user_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession,
    *,
    active: bool,
) -> UserResponse:
    service = _build_service(request, session)
    try:
        user = await service.set_active(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            user_id=user_id,
            active=active,
            request_id=request.headers.get("x-request-id"),
        )
    except UserNotFound as error:
        raise _not_found() from error
    except UnsafeUserChange as error:
        raise _unprocessable(str(error)) from error

    await session.commit()
    return _response(user)


@router.post(
    "/{user_id}/password",
    response_model=UserResponse,
    responses={
        403: {"description": "Insufficient role"},
        404: {"description": "Not found"},
        422: {"description": "Weak password"},
    },
)
async def set_user_password(
    user_id: uuid.UUID,
    payload: SetPasswordRequest,
    request: Request,
    current_user: _AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    """Define a senha de outro usuário e revoga as sessões dele."""
    service = _build_service(request, session)
    try:
        user = await service.set_password(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.user_id,
            user_id=user_id,
            password=payload.password.get_secret_value(),
            request_id=request.headers.get("x-request-id"),
        )
    except UserNotFound as error:
        raise _not_found() from error
    except WeakPassword as error:
        raise _unprocessable(str(error)) from error

    await session.commit()
    return _response(user)
