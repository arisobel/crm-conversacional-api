import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, get_current_user
from crm_api.core.config import Settings
from crm_api.core.database import get_session
from crm_api.models.whatsapp_connection import RepresentativeWhatsappConnection
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.users import UserRepository
from crm_api.repositories.whatsapp_connections import WhatsappConnectionRepository
from crm_api.schemas.whatsapp_connections import WhatsappConnectionResponse
from crm_api.services.gateway_whatsapp_onboarding import (
    GatewayOnboardingError,
    GatewayWhatsappOnboardingClient,
)
from crm_api.services.whatsapp_connections import (
    ConnectionConflict,
    ConnectionForbidden,
    ConnectionNotFound,
    WhatsappConnectionService,
    retry_action_for,
)
from crm_api.web.csrf import csrf_is_valid

router = APIRouter(prefix="/api/v1/representatives", tags=["WhatsApp onboarding"])


def _service(request: Request, session: AsyncSession) -> WhatsappConnectionService:
    return WhatsappConnectionService(
        connections=WhatsappConnectionRepository(session),
        users=UserRepository(session),
        audit=AuditRepository(session),
        gateway=GatewayWhatsappOnboardingClient(request.app.state.settings),
    )


def _response(
    connection: RepresentativeWhatsappConnection, launch_url: str | None = None
) -> WhatsappConnectionResponse:
    return WhatsappConnectionResponse(
        connection_id=connection.id,
        representative_user_id=connection.representative_user_id,
        status=connection.status,
        display_phone_number=connection.display_phone_number,
        failure_code=connection.failure_code,
        started_at=connection.started_at,
        connected_at=connection.connected_at,
        launch_url=launch_url,
        retry_action=retry_action_for(connection),
    )


def _raise(error: Exception) -> None:
    if isinstance(error, ConnectionNotFound):
        raise HTTPException(404, "representative not found") from error
    if isinstance(error, ConnectionForbidden):
        raise HTTPException(403, "not allowed for this representative") from error
    if isinstance(error, ConnectionConflict):
        raise HTTPException(409, "an active or non-resumable connection already exists") from error
    if isinstance(error, GatewayOnboardingError):
        raise HTTPException(error.status_code, str(error)) from error
    raise error


def _csrf(request: Request) -> None:
    if not csrf_is_valid(request, request.headers.get("x-csrf-token")):
        raise HTTPException(400, "csrf validation failed")


def _full_launch_url(settings: Settings, launch_url: str | None) -> str | None:
    """A URL só é entregue quando o Gateway realmente a retornou."""
    if launch_url is None:
        return None
    # O cliente do Gateway só aceita URL relativa e requer base configurada.
    return f"{settings.whatsapp_gateway_base_url.rstrip('/')}{launch_url}"


@router.post(
    "/{user_id}/whatsapp-connection",
    response_model=WhatsappConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    user_id: uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WhatsappConnectionResponse:
    _csrf(request)
    try:
        connection, launch = await _service(request, session).create(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.user_id,
            role=current_user.role,
            representative_id=user_id,
            tenant_reference=request.app.state.settings.tenant_slug,
            request_id=request.headers.get("x-request-id"),
        )
        await session.commit()
        return _response(
            connection,
            _full_launch_url(request.app.state.settings, launch),
        )
    except Exception as error:
        await session.rollback()
        _raise(error)


@router.get("/{user_id}/whatsapp-connection", response_model=WhatsappConnectionResponse | None)
async def get_connection(
    user_id: uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WhatsappConnectionResponse | None:
    try:
        connection = await _service(request, session).get(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.user_id,
            role=current_user.role,
            representative_id=user_id,
            request_id=request.headers.get("x-request-id"),
        )
        await session.commit()
        return _response(connection) if connection else None
    except Exception as error:
        await session.rollback()
        _raise(error)


@router.post("/{user_id}/whatsapp-connection/resume", response_model=WhatsappConnectionResponse)
async def resume_connection(
    user_id: uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WhatsappConnectionResponse:
    _csrf(request)
    try:
        connection, launch = await _service(request, session).resume(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.user_id,
            role=current_user.role,
            representative_id=user_id,
            request_id=request.headers.get("x-request-id"),
        )
        await session.commit()
        return _response(
            connection,
            _full_launch_url(request.app.state.settings, launch),
        )
    except Exception as error:
        await session.rollback()
        _raise(error)
