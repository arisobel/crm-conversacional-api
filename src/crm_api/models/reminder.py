"""Compromissos e lembretes comerciais criados pelas conversas do WhatsApp."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base


class ReminderStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReminderOrigin(StrEnum):
    CUSTOMER = "CUSTOMER"
    REPRESENTATIVE = "REPRESENTATIVE"


class ReminderKind(StrEnum):
    CALL = "CALL"
    MEETING = "MEETING"
    FOLLOW_UP = "FOLLOW_UP"


class RepresentativeReminder(Base):
    __tablename__ = "representative_reminders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_wamid", name="ux_reminder_source_wamid"),
        CheckConstraint(
            "status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'COMPLETED', 'CANCELLED')",
            name="ck_reminder_status",
        ),
        CheckConstraint("origin IN ('CUSTOMER', 'REPRESENTATIVE')", name="ck_reminder_origin"),
        CheckConstraint("kind IN ('CALL', 'MEETING', 'FOLLOW_UP')", name="ck_reminder_kind"),
        Index("ix_reminders_due", "status", "due_at"),
        Index("ix_reminders_representative", "representative_user_id", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    representative_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    customer_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_contacts.id"), nullable=True
    )
    origin: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    source_wamid: Mapped[str] = mapped_column(String(255))
    source_line_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notification_claim_token: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

