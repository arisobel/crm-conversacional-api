"""Contatos e localidades de um cliente.

Ambos são sempre alcançados pelo `customer_id`, que passa pelo escopo de
carteira. Não existe rota que leia um contato ou uma localidade por id solto.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, get_current_user
from crm_api.api.scoping import build_customer_admin_service, scope_for, translated_errors
from crm_api.core.database import get_session
from crm_api.models.customer import CustomerLocation
from crm_api.models.customer_contact import CustomerContact
from crm_api.schemas.customer_admin import (
    ContactResponse,
    CreateContactRequest,
    CreateLocationRequest,
    LocationResponse,
    UpdateContactRequest,
    UpdateLocationRequest,
)

router = APIRouter(prefix="/admin/customers/{customer_id}", tags=["Customer Records"])

_NOT_FOUND = {404: {"description": "Customer, contact or location not found"}}
_CONFLICT = {409: {"description": "Already used within the tenant"}}


def _contact(contact: CustomerContact) -> ContactResponse:
    return ContactResponse(
        contact_id=contact.id,
        name=contact.name,
        whatsapp_e164=contact.whatsapp_e164,
        is_primary=contact.is_primary,
        active=contact.active,
    )


def _location(location: CustomerLocation) -> LocationResponse:
    return LocationResponse(
        location_id=location.id,
        label=location.label,
        state_code=location.state_code,
        city=location.city,
        is_default=location.is_default,
        active=location.active,
    )


@router.get("/contacts", response_model=list[ContactResponse], responses=_NOT_FOUND)
async def list_contacts(
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ContactResponse]:
    with translated_errors():
        contacts = await build_customer_admin_service(session).list_contacts(
            scope_for(current_user), customer_id
        )
    return [_contact(contact) for contact in contacts]


@router.post(
    "/contacts",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_NOT_FOUND | _CONFLICT | {422: {"description": "Invalid phone"}},
)
async def create_contact(
    customer_id: uuid.UUID,
    payload: CreateContactRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContactResponse:
    """Marcar este contato como principal desmarca o anterior na mesma transação."""
    service = build_customer_admin_service(session)
    with translated_errors():
        contact = await service.create_contact(
            scope_for(current_user),
            customer_id,
            actor_user_id=current_user.user_id,
            name=payload.name,
            whatsapp_e164=payload.whatsapp_e164,
            is_primary=payload.is_primary,
            request_id=request.headers.get("x-request-id"),
        )
    await session.commit()
    return _contact(contact)


@router.patch(
    "/contacts/{contact_id}",
    response_model=ContactResponse,
    responses=_NOT_FOUND | _CONFLICT | {422: {"description": "Invalid phone"}},
)
async def update_contact(
    customer_id: uuid.UUID,
    contact_id: uuid.UUID,
    payload: UpdateContactRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContactResponse:
    """Desativar um contato também retira dele a marca de principal."""
    service = build_customer_admin_service(session)
    with translated_errors():
        contact = await service.update_contact(
            scope_for(current_user),
            customer_id,
            contact_id,
            actor_user_id=current_user.user_id,
            name=payload.name,
            whatsapp_e164=payload.whatsapp_e164,
            is_primary=payload.is_primary,
            active=payload.active,
            request_id=request.headers.get("x-request-id"),
        )
    await session.commit()
    return _contact(contact)


@router.get("/locations", response_model=list[LocationResponse], responses=_NOT_FOUND)
async def list_locations(
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[LocationResponse]:
    with translated_errors():
        locations = await build_customer_admin_service(session).list_locations(
            scope_for(current_user), customer_id
        )
    return [_location(location) for location in locations]


@router.post(
    "/locations",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_NOT_FOUND | {422: {"description": "Invalid state code"}},
)
async def create_location(
    customer_id: uuid.UUID,
    payload: CreateLocationRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LocationResponse:
    """A primeira localidade ativa de um cliente vira a padrão automaticamente."""
    service = build_customer_admin_service(session)
    with translated_errors():
        location = await service.create_location(
            scope_for(current_user),
            customer_id,
            actor_user_id=current_user.user_id,
            label=payload.label,
            state_code=payload.state_code,
            city=payload.city,
            is_default=payload.is_default,
            request_id=request.headers.get("x-request-id"),
        )
    await session.commit()
    return _location(location)


@router.patch(
    "/locations/{location_id}",
    response_model=LocationResponse,
    responses=_NOT_FOUND | {422: {"description": "Invalid state code or default required"}},
)
async def update_location(
    customer_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: UpdateLocationRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LocationResponse:
    """Desativar ou desmarcar a localidade padrão exige promover outra antes."""
    service = build_customer_admin_service(session)
    with translated_errors():
        location = await service.update_location(
            scope_for(current_user),
            customer_id,
            location_id,
            actor_user_id=current_user.user_id,
            label=payload.label,
            state_code=payload.state_code,
            city=payload.city,
            is_default=payload.is_default,
            active=payload.active,
            request_id=request.headers.get("x-request-id"),
        )
    await session.commit()
    return _location(location)
