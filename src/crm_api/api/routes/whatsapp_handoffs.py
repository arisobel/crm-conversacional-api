"""Handoff e agenda comercial, sem expor carteira ao Gateway."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.core.phone import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.models.customer import Customer, Tenant
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.reminder import ReminderOrigin, ReminderStatus, RepresentativeReminder
from crm_api.models.user import User, UserRole
from crm_api.models.whatsapp_connection import (
    RepresentativeWhatsappConnection,
    WhatsappConnectionStatus,
)
from crm_api.repositories.reminders import ReminderRepository
from crm_api.schemas.reminders import CustomerReminderRequest, CustomerReminderResponse
from crm_api.schemas.whatsapp_handoffs import HandoffReminderRequest, HandoffReminderResponse

router = APIRouter(tags=["WhatsApp Handoffs"])


async def _customer_owner_for_line(session, tenant_slug: str, line_reference: str, phone: str):
    return (
        await session.execute(
            select(User, Customer, CustomerContact, Tenant)
            .join(Tenant, Tenant.id == User.tenant_id)
            .join(
                RepresentativeWhatsappConnection,
                RepresentativeWhatsappConnection.representative_user_id == User.id,
            )
            .join(Customer, Customer.owner_user_id == User.id)
            .join(CustomerContact, CustomerContact.customer_id == Customer.id)
            .where(
                Tenant.slug == tenant_slug,
                RepresentativeWhatsappConnection.gateway_line_reference == line_reference,
                RepresentativeWhatsappConnection.status == WhatsappConnectionStatus.CONNECTED,
                CustomerContact.whatsapp_e164 == phone,
                CustomerContact.active.is_(True),
                Customer.active.is_(True),
                User.active.is_(True),
                User.role == UserRole.REPRESENTATIVE,
            )
        )
    ).first()


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


@router.post("/internal/whatsapp/customer-reminders", response_model=CustomerReminderResponse)
async def create_customer_reminder(
    payload: CustomerReminderRequest,
    _: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CustomerReminderResponse:
    """Registra o pedido do cliente sem interromper a conversa Coexistence."""
    try:
        phone = normalize_whatsapp_e164(payload.customer_phone_e164)
    except InvalidWhatsappNumber as error:
        raise HTTPException(status_code=422, detail="invalid customer phone") from error
    if payload.due_at.tzinfo is None or payload.due_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="due_at requires timezone")
    due_at = payload.due_at.astimezone(UTC)
    now = datetime.now(UTC)
    if due_at <= now or due_at > now + timedelta(days=366):
        raise HTTPException(status_code=422, detail="reminder due_at outside supported range")

    row = await _customer_owner_for_line(
        session, tenant_slug, payload.gateway_line_reference, phone
    )
    if row is None or not row[0].whatsapp_e164:
        raise HTTPException(status_code=403, detail="customer reminder context denied")
    representative, customer, contact, tenant = row
    repository = ReminderRepository(session)
    reminder = await repository.get_by_source(tenant.id, payload.source_wamid)
    created = reminder is None
    if reminder is None:
        due_local = due_at.astimezone(ZoneInfo("America/Sao_Paulo"))
        slot_start = due_local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
        conflict = await repository.find_slot_conflict(
            tenant.id,
            representative.id,
            slot_start,
            slot_start + timedelta(hours=1),
        )
        if conflict is not None:
            raise HTTPException(status_code=409, detail="representative reminder slot conflict")
        reminder = RepresentativeReminder(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            representative_user_id=representative.id,
            customer_id=customer.id,
            customer_contact_id=contact.id,
            origin=ReminderOrigin.CUSTOMER.value,
            kind=payload.kind,
            # O próprio cliente pediu o compromisso; não há uma segunda
            # confirmação para o robô cobrar do representante.
            status=ReminderStatus.CONFIRMED.value,
            note=payload.note.strip(),
            due_at=due_at,
            timezone="America/Sao_Paulo",
            source_wamid=payload.source_wamid,
            source_line_reference=payload.gateway_line_reference,
        )
        repository.add(reminder)
        await session.commit()
    return CustomerReminderResponse(
        created=created,
        reminder_id=reminder.id,
        status=reminder.status,
        representative_phone_e164=representative.whatsapp_e164,
        representative_name=representative.full_name,
        customer_name=customer.legal_name,
        due_at=reminder.due_at,
        kind=reminder.kind,
    )
