import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base


class IcmsRule(Base):
    """Alíquota de ICMS para um par de UFs, com especialização opcional.

    A venda interestadual depende do par `origem → destino`, e não apenas da UF
    do cliente — por isso a regra carrega as duas pontas. `product_id` e
    `family_id` são níveis diferentes de especificidade e são mutuamente
    exclusivos; aceitar os dois tornaria a precedência ambígua.
    """

    __tablename__ = "icms_rules"
    __table_args__ = (
        Index(
            "ix_icms_rules_lookup",
            "tenant_id",
            "origin_state",
            "destination_state",
            "valid_from",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    origin_state: Mapped[str] = mapped_column(String(2))
    destination_state: Mapped[str] = mapped_column(String(2))
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_families.id"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True
    )
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def especificidade(self) -> int:
        """Posição na ordem de precedência; maior vence.

        A escala é fixa e declarada aqui, junto do dado, para que a regra de
        desempate não fique espalhada pelo serviço.
        """
        if self.customer_id is not None and self.product_id is not None:
            return 6
        if self.customer_id is not None and self.family_id is not None:
            return 5
        if self.customer_id is not None:
            return 4
        if self.product_id is not None:
            return 3
        if self.family_id is not None:
            return 2
        return 1
