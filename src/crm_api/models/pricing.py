import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
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


class PriceListStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    # Estado terminal do lote de importação: seus valores já foram promovidos
    # para `price_entries`, que é a fonte de verdade desde a migração `0006`.
    PUBLISHED = "PUBLISHED"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    SUSPENDED = "SUSPENDED"
    FUTURE_ARRIVAL = "FUTURE_ARRIVAL"
    CONSULT = "CONSULT"


class PriceList(Base):
    __tablename__ = "price_lists"
    __table_args__ = (UniqueConstraint("tenant_id", "name", "reference_month"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    reference_month: Mapped[date] = mapped_column(Date)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    base_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    status: Mapped[PriceListStatus] = mapped_column(
        SqlEnum(PriceListStatus, name="price_list_status"), default=PriceListStatus.DRAFT
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PriceListItem(Base):
    __tablename__ = "price_list_items"
    __table_args__ = (UniqueConstraint("price_list_id", "product_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    price_list_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_lists.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    availability: Mapped[AvailabilityStatus] = mapped_column(
        SqlEnum(AvailabilityStatus, name="availability_status"),
        default=AvailabilityStatus.CONSULT,
    )
    expected_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    available_quantity_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    arrival_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class PriceEntry(Base):
    """Preço vigente de um produto em uma competência.

    Fonte de verdade desde a `0006`. A chave `(tenant, competência, produto)` é
    a idempotência comercial do ADR-014: republicar o mesmo mês corrige o preço,
    nunca cria uma segunda tabela.
    """

    __tablename__ = "price_entries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "reference_month", "product_id", name="ux_price_entry_month_product"
        ),
        Index("ix_price_entries_month", "tenant_id", "reference_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    reference_month: Mapped[date] = mapped_column(Date)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    # ICMS já embutido em `base_price`. É o que permite converter o preço para
    # outra UF sem cobrar imposto duas vezes. Ver Q1 da direção do produto.
    base_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    availability: Mapped[AvailabilityStatus] = mapped_column(
        SqlEnum(AvailabilityStatus, name="availability_status"),
        default=AvailabilityStatus.CONSULT,
    )
    expected_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    available_quantity_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    arrival_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("price_lists.id"), nullable=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class PriceEntryRevision(Base):
    """Histórico append-only de cada gravação de preço.

    É o que responde "por que o preço do produto X mudou no dia 20" — o caso
    concreto da tabela especial de 20/07/2026, que neste modelo é uma revisão
    dentro da competência, e não uma segunda tabela.
    """

    __tablename__ = "price_entry_revisions"
    __table_args__ = (
        Index(
            "ix_price_entry_revisions_product",
            "tenant_id",
            "reference_month",
            "product_id",
            "changed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    reference_month: Mapped[date] = mapped_column(Date)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    previous: Mapped[dict | None] = mapped_column(_JSON_COLUMN, nullable=True)
    current: Mapped[dict] = mapped_column(_JSON_COLUMN)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("price_lists.id"), nullable=True
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
