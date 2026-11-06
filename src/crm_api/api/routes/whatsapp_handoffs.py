"""Handoff e agenda comercial, sem expor carteira ao Gateway."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
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
from crm_api.schemas.reminders import (
    CustomerReminderRequest,
    CustomerReminderResponse,
    ReminderNotificationAckRequest,
    ReminderNotificationClaimRequest,
    ReminderNotificationClaimResponse,
    ReminderNotificationItem,
)
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


@router.post(
    "/internal/whatsapp/reminder-notifications/claim",
    response_model=ReminderNotificationClaimResponse,
)
async def claim_reminder_notifications(
    payload: ReminderNotificationClaimRequest,
    _: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReminderNotificationClaimResponse:
    """Reserva avisos da próxima hora; uma reserva abandonada expira em 5 minutos."""
    now = datetime.now(UTC)
    stale = now - timedelta(minutes=5)
    rows = (
        await session.execute(
            select(RepresentativeReminder, User, Customer)
            .join(User, User.id == RepresentativeReminder.representative_user_id)
            .join(Tenant, Tenant.id == RepresentativeReminder.tenant_id)
            .outerjoin(Customer, Customer.id == RepresentativeReminder.customer_id)
            .where(
                Tenant.slug == tenant_slug,
                User.active.is_(True),
                User.role == UserRole.REPRESENTATIVE,
                User.whatsapp_e164.is_not(None),
                RepresentativeReminder.status == ReminderStatus.CONFIRMED.value,
                RepresentativeReminder.notified_at.is_(None),
                RepresentativeReminder.due_at > now,
                RepresentativeReminder.due_at <= now + timedelta(hours=1),
                or_(
                    RepresentativeReminder.notification_claimed_at.is_(None),
                    RepresentativeReminder.notification_claimed_at < stale,
                ),
            )
            .order_by(RepresentativeReminder.due_at, RepresentativeReminder.id)
            .limit(payload.limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    claimed: list[ReminderNotificationItem] = []
    for reminder, representative, customer in rows:
        token = uuid.uuid4()
        reminder.notification_claimed_at = now
        reminder.notification_claim_token = token
        claimed.append(
            ReminderNotificationItem(
                reminder_id=reminder.id,
                claim_token=token,
                representative_phone_e164=representative.whatsapp_e164,
                representative_name=representative.full_name,
                customer_name=customer.legal_name if customer is not None else None,
                due_at=reminder.due_at,
                kind=reminder.kind,
                note=reminder.note,
            )
        )
    await session.commit()
    return ReminderNotificationClaimResponse(reminders=claimed)


@router.post("/internal/whatsapp/reminder-notifications/ack")
async def acknowledge_reminder_notification(
    payload: ReminderNotificationAckRequest,
    _: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    reminder = await session.scalar(
        select(RepresentativeReminder)
        .join(Tenant, Tenant.id == RepresentativeReminder.tenant_id)
        .where(
            Tenant.slug == tenant_slug,
            RepresentativeReminder.id == payload.reminder_id,
            RepresentativeReminder.notification_claim_token == payload.claim_token,
        )
        .with_for_update()
    )
    if reminder is None:
        raise HTTPException(status_code=409, detail="reminder notification claim not found")
    if payload.delivered:
        reminder.notified_at = datetime.now(UTC)
    reminder.notification_claimed_at = None
    reminder.notification_claim_token = None
    await session.commit()
    return {"acknowledged": True}
