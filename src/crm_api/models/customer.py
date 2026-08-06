import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from crm_api.models.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    # UF do estabelecimento que fatura. Origem do par que determina o ICMS.
    # Nula até ser configurada; o cálculo falha explicitamente sem ela, em vez
    # de assumir uma origem e produzir um preço plausível e errado.
    origin_state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (CheckConstraint("state_code GLOB '[A-Z][A-Z]'", name="ck_customers_state"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    legal_name: Mapped[str] = mapped_column(Text)
    trade_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_code: Mapped[str] = mapped_column(String(2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Titular vigente da conta. Nulável porque um cliente pode existir sem
    # representante designado — e porque a base atual não tem titular algum.
    # O histórico de titularidade vive em `CustomerAssignmentHistory`.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship()


class CustomerLocation(Base):
    """Onde o cliente recebe.

    O ICMS depende da UF de destino, e um cliente pode receber em mais de uma.
    `Customer.state_code` permanece como UF fiscal do cadastro; a resolução de
    preço passa a usar a localidade.
    """

    __tablename__ = "customer_locations"
    __table_args__ = (
        # No máximo uma localidade simultaneamente padrão e ativa por cliente.
        # Índice parcial: uma UNIQUE comum barraria também as não-padrão.
        Index(
            "ux_default_location_per_customer",
            "customer_id",
            unique=True,
            sqlite_where=text("is_default AND active"),
            postgresql_where=text("is_default AND active"),
        ),
        Index("ix_customer_locations_customer", "customer_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    label: Mapped[str] = mapped_column(Text)
    state_code: Mapped[str] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomerAssignmentHistory(Base):
    """Trilha append-only da titularidade da conta.

    Existe para responder "quem atendia esta conta em março" sem obrigar toda
    consulta de carteira a percorrer vigências — por isso o titular atual é
    denormalizado em `Customer.owner_user_id`.
    """

    __tablename__ = "customer_assignment_history"
    __table_args__ = (
        Index("ix_customer_assignment_history_customer", "customer_id", "assigned_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    # Nulo registra a remoção do titular, que também é um evento auditável.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

