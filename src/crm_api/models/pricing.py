import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base


class PriceListStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


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
