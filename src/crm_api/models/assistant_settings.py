"""Configuração comercial da linha assistente; não controla o Gateway ainda."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base
from crm_api.models.customer import Tenant  # noqa: F401
from crm_api.models.user import User  # noqa: F401

_JSON_COLUMN = JSON().with_variant(JSONB(), "postgresql")


class AssistantOrganizationSettings(Base):
    __tablename__ = "assistant_organization_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantRepresentativeSettings(Base):
    __tablename__ = "assistant_representative_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_assistant_rep_user_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantRepresentativeCapability(Base):
    __tablename__ = "assistant_representative_capabilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            [
                "assistant_representative_settings.tenant_id",
                "assistant_representative_settings.user_id",
            ],
            name="fk_assistant_capability_rep",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(80), primary_key=True)


class ConversationBehaviorSettings(Base):
    """Configuração preparada para o Gateway, sem efeito no atendimento atual."""

    __tablename__ = "conversation_behavior_settings"
    __table_args__ = (
        CheckConstraint("bot_kind IN ('ASSISTANT', 'COEXISTENCE')", name="ck_behavior_bot_kind"),
        CheckConstraint("context_minutes BETWEEN 15 AND 1440", name="ck_behavior_context_minutes"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    bot_kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    tone: Mapped[str] = mapped_column(String(40), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    context_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationSimulationScenario(Base):
    """Caso de regressão salvo pelo administrador, sempre executado sem escrita."""

    __tablename__ = "conversation_simulation_scenarios"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('REPRESENTATIVE_ASSISTANT', 'CUSTOMER_SERVICE')",
            name="ck_simulation_scenario_mode",
        ),
        CheckConstraint(
            "max_questions IS NULL OR max_questions BETWEEN 0 AND 5",
            name="ck_simulation_scenario_max_questions",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(32))
    representative_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    conversation_history: Mapped[list[dict[str, str]]] = mapped_column(
        _JSON_COLUMN, default=list, server_default=text("'[]'"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text)
    expected_status: Mapped[str] = mapped_column(String(32))
    expected_capability_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expected_action: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expected_fact_text: Mapped[str | None] = mapped_column(String(240), nullable=True)
    expected_reply_contains: Mapped[str | None] = mapped_column(Text, nullable=True)
    forbidden_reply_contains: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_questions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MvpReleaseControl(Base):
    """Evidências e escopo aprovados para liberar uma versão do MVP."""

    __tablename__ = "mvp_release_controls"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    scope_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="MVP-1", server_default=text("'MVP-1'")
    )
    scope_frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scope_frozen_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    scope_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope_snapshot: Mapped[dict | None] = mapped_column(_JSON_COLUMN, nullable=True)
    acceptance_checks: Mapped[dict] = mapped_column(
        _JSON_COLUMN, default=dict, server_default=text("'{}'"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
