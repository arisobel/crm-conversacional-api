import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base

_JSON_COLUMN = JSON().with_variant(JSONB(), "postgresql")

WHATSAPP_CHANNEL = "WHATSAPP"
GATEWAY_SOURCE = "whatsapp-gateway"


class InteractionDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class CustomerInteraction(Base):
    """Uma linha da história de um cliente, projetada de outro sistema.

    O CRM não é dono da conversa (ADR-016): a origem continua sendo o Gateway, e
    esta tabela guarda apenas o suficiente para montar a linha do tempo da ficha
    sem consultá-lo. Nunca sofre `UPDATE` — reprocessar o mesmo evento é
    reconhecido pela unicidade de `(tenant_id, source, external_ref)` e
    descartado, não regravado.
    """

    __tablename__ = "customer_interactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "external_ref", name="ux_interaction_source_ref"),
        Index("ix_customer_interactions_timeline", "customer_id", "occurred_at"),
        Index("ix_customer_interactions_occurred", "tenant_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_contacts.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(Text, default=WHATSAPP_CHANNEL)
    direction: Mapped[InteractionDirection] = mapped_column(
        SqlEnum(InteractionDirection, name="interaction_direction")
    )
    source: Mapped[str] = mapped_column(Text)
    external_ref: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(_JSON_COLUMN, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
