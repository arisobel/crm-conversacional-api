"""Configuração comercial da linha assistente; não controla o Gateway ainda."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base
from crm_api.models.customer import Tenant  # noqa: F401
from crm_api.models.user import User  # noqa: F401


class AssistantOrganizationSettings(Base):
    __tablename__ = "assistant_organization_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantRepresentativeSettings(Base):
    __tablename__ = "assistant_representative_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
            name="fk_assistant_rep_user_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantRepresentativeCapability(Base):
    __tablename__ = "assistant_representative_capabilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["assistant_representative_settings.tenant_id", "assistant_representative_settings.user_id"],
            name="fk_assistant_capability_rep",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(80), primary_key=True)
