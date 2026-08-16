import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from crm_api.core.identifiers import new_public_ref
from crm_api.models.base import Base
from crm_api.models.customer import Customer


class CustomerContact(Base):
    __tablename__ = "customer_contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "whatsapp_e164"),
        UniqueConstraint("public_ref", name="ux_customer_contacts_public_ref"),
        # Já existia no DDL desde a `0001`; o modelo só passa a declará-lo em R2
        # para que o invariante também valha nos testes.
        Index(
            "ux_primary_contact_per_customer",
            "customer_id",
            unique=True,
            sqlite_where=text("is_primary AND active"),
            postgresql_where=text("is_primary AND active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    whatsapp_e164: Mapped[str] = mapped_column(String(16))
    public_ref: Mapped[str] = mapped_column(String(24), default=new_public_ref)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customer: Mapped[Customer] = relationship()

