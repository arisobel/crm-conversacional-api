"""Consulta privada para lembrete ao representante, sem expor carteira ao Gateway."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.core.phone import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.models.customer import Customer, Tenant
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import User, UserRole
from crm_api.models.whatsapp_connection import (
    RepresentativeWhatsappConnection,
    WhatsappConnectionStatus,
)
from crm_api.schemas.whatsapp_handoffs import HandoffReminderRequest, HandoffReminderResponse

router = APIRouter(tags=["WhatsApp Handoffs"])


@router.post("/internal/whatsapp/handoff-reminder", response_model=HandoffReminderResponse)
async def handoff_reminder_target(
    payload: HandoffReminderRequest,
    _: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HandoffReminderResponse:
    """Só devolve o destinatário se linha, cliente e titular ainda coincidirem."""
    try:
        phone = normalize_whatsapp_e164(payload.customer_phone_e164)
    except InvalidWhatsappNumber:
        return HandoffReminderResponse(decision="DENY")
    row = (
        await session.execute(
            select(User, Customer)
            .join(Tenant, Tenant.id == User.tenant_id)
            .join(
                RepresentativeWhatsappConnection,
                RepresentativeWhatsappConnection.representative_user_id == User.id,
            )
            .join(Customer, Customer.owner_user_id == User.id)
            .join(CustomerContact, CustomerContact.customer_id == Customer.id)
            .where(
                Tenant.slug == tenant_slug,
                RepresentativeWhatsappConnection.gateway_line_reference
                == payload.gateway_line_reference,
                RepresentativeWhatsappConnection.status == WhatsappConnectionStatus.CONNECTED,
                CustomerContact.whatsapp_e164 == phone,
                CustomerContact.active.is_(True),
                Customer.active.is_(True),
                User.active.is_(True),
                User.role == UserRole.REPRESENTATIVE,
            )
        )
    ).first()
    if row is None or not row[0].whatsapp_e164:
        return HandoffReminderResponse(decision="DENY")
    representative, customer = row
    return HandoffReminderResponse(
        decision="ALLOW",
        representative_phone_e164=representative.whatsapp_e164,
        representative_name=representative.full_name,
        customer_name=customer.legal_name,
    )
