"""Indicadores operacionais dos robôs, calculados apenas com dados do CRM."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer_intake import CustomerIntake, IntakeStatus
from crm_api.models.interaction import (
    GATEWAY_SOURCE,
    CustomerInteraction,
    InteractionDirection,
    InteractionKind,
)
from crm_api.models.reminder import ReminderStatus, RepresentativeReminder
from crm_api.models.user import AuditLog

_RECOVERY_OUTCOMES = frozenset({"FALLBACK", "RECOVERY"})
_CONFIRMED_ACTIONS = frozenset(
    {
        "PRICE_BATCH_PUBLISHED",
        "CUSTOMER_INTAKE_ACCEPTED",
        "WHATSAPP_CAMPAIGN_DRAFT_CREATED",
        "reminder.created",
    }
)


@dataclass(frozen=True)
class AssistantMonitoringSnapshot:
    status: str
    customer_messages_24h: int
    representative_messages_24h: int
    responses_24h: int
    recoveries_24h: int
    out_of_scope_24h: int
    comprehension_percent: int | None
    handoffs_7d: int
    upcoming_reminders_24h: int
    overdue_reminders: int
    notifications_sent_7d: int
    confirmed_actions_7d: int
    pending_intakes: int
    stale_pending_intakes: int
    latest_activity_at: datetime | None
    alerts: tuple[str, ...]


async def assistant_monitoring_snapshot(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> AssistantMonitoringSnapshot:
    now = now or datetime.now(UTC)
    last_day = now - timedelta(hours=24)
    last_week = now - timedelta(days=7)

    interactions = list(
        await session.scalars(
            select(CustomerInteraction).where(
                CustomerInteraction.tenant_id == tenant_id,
                CustomerInteraction.source == GATEWAY_SOURCE,
                CustomerInteraction.occurred_at >= last_week,
            )
        )
    )
    recent = [item for item in interactions if _aware(item.occurred_at) >= last_day]
    outbound = [
        item for item in recent if item.direction is InteractionDirection.OUTBOUND
    ]
    outcomes = [
        str((item.payload or {}).get("outcome") or "").upper() for item in outbound
    ]
    recoveries = sum(outcome in _RECOVERY_OUTCOMES for outcome in outcomes)
    comprehension = (
        round(100 * (len(outbound) - recoveries) / len(outbound)) if outbound else None
    )

    reminders = list(
        await session.scalars(
            select(RepresentativeReminder).where(
                RepresentativeReminder.tenant_id == tenant_id,
                RepresentativeReminder.status == ReminderStatus.CONFIRMED.value,
            )
        )
    )
    overdue = sum(
        _aware(item.due_at) < now and item.notified_at is None for item in reminders
    )
    upcoming = sum(
        now <= _aware(item.due_at) <= now + timedelta(hours=24) for item in reminders
    )
    notified = sum(
        item.notified_at is not None and _aware(item.notified_at) >= last_week
        for item in reminders
    )
    actions = list(
        await session.scalars(
            select(AuditLog.action).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.occurred_at >= last_week,
                AuditLog.action.in_(_CONFIRMED_ACTIONS),
            )
        )
    )
    pending_intake_dates = list(
        await session.scalars(
            select(CustomerIntake.created_at).where(
                CustomerIntake.tenant_id == tenant_id,
                CustomerIntake.status == IntakeStatus.PENDING,
            )
        )
    )
    stale_pending_intakes = sum(
        _aware(created_at) <= now - timedelta(hours=24)
        for created_at in pending_intake_dates
    )

    alerts: list[str] = []
    if overdue:
        alerts.append(
            f"{overdue} lembrete(s) venceu(ram) sem confirmação de envio."
        )
    if comprehension is not None and comprehension < 85:
        alerts.append(
            "A taxa de compreensão das últimas 24 horas está abaixo de 85%."
        )
    if not recent:
        alerts.append("Nenhuma atividade dos robôs foi registrada nas últimas 24 horas.")
    if stale_pending_intakes:
        alerts.append(
            f"{stale_pending_intakes} pré-cadastro(s) aguarda(m) conferência há mais de 24 horas."
        )

    return AssistantMonitoringSnapshot(
        status=(
            "ATTENTION"
            if overdue
            or stale_pending_intakes
            or (comprehension is not None and comprehension < 85)
            else "OK"
        ),
        customer_messages_24h=sum(
            item.direction is InteractionDirection.INBOUND
            and item.kind is InteractionKind.CUSTOMER_CHANNEL
            for item in recent
        ),
        representative_messages_24h=sum(
            item.direction is InteractionDirection.INBOUND
            and item.kind is InteractionKind.ACTOR_CHANNEL
            for item in recent
        ),
        responses_24h=len(outbound),
        recoveries_24h=recoveries,
        out_of_scope_24h=sum(outcome == "OUT_OF_SCOPE" for outcome in outcomes),
        comprehension_percent=comprehension,
        handoffs_7d=sum(
            item.direction is InteractionDirection.OUTBOUND
            and str((item.payload or {}).get("outcome") or "").upper() == "HUMAN_HANDOFF"
            for item in interactions
        ),
        upcoming_reminders_24h=upcoming,
        overdue_reminders=overdue,
        notifications_sent_7d=notified,
        confirmed_actions_7d=len(actions),
        pending_intakes=len(pending_intake_dates),
        stale_pending_intakes=stale_pending_intakes,
        latest_activity_at=max(
            (_aware(item.occurred_at) for item in interactions), default=None
        ),
        alerts=tuple(alerts),
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
