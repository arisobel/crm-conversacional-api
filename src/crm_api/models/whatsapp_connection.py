"""Vínculo comercial entre um usuário representante e uma linha do Gateway."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, func, text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base


class WhatsappConnectionStatus(StrEnum):
    NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    CONFLICT = "CONFLICT"
    FAILED = "FAILED"


class RepresentativeWhatsappConnection(Base):
    """Projeção comercial; nunca contém segredo, URL de launch ou payload Meta."""

    __tablename__ = "representative_whatsapp_connections"
    __table_args__ = (
        Index(
            "ux_rwc_one_active_per_representative",
            "tenant_id",
            "representative_user_id",
            unique=True,
            sqlite_where=text("status IN ('CONNECTING', 'CONNECTED', 'ACTION_REQUIRED')"),
            postgresql_where=text("status IN ('CONNECTING', 'CONNECTED', 'ACTION_REQUIRED')"),
        ),
        Index("ux_rwc_gateway_onboarding", "tenant_id", "gateway_onboarding_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    representative_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="whatsapp")
    status: Mapped[WhatsappConnectionStatus] = mapped_column(
        SqlEnum(WhatsappConnectionStatus, name="whatsapp_connection_status"),
        default=WhatsappConnectionStatus.CONNECTING,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    gateway_onboarding_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    gateway_line_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_phone_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_gateway_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
