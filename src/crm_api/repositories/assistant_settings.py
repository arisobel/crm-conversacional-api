"""Leitura isolada por tenant da configuração do assistente."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.assistant_settings import (
    AssistantOrganizationSettings,
    AssistantRepresentativeCapability,
    AssistantRepresentativeSettings,
)
from crm_api.models.user import User, UserRole
from crm_api.services.assistant_policy import AssistantPolicy


async def get_assistant_policy(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> AssistantPolicy:
    """Ausência de dados, usuário inativo ou fora do tenant resulta em negação."""
    user = await session.scalar(select(User).where(
        User.id == user_id, User.tenant_id == tenant_id,
        User.active.is_(True), User.role == UserRole.REPRESENTATIVE,
    ))
    if user is None:
        return AssistantPolicy()
    organization = await session.get(AssistantOrganizationSettings, tenant_id)
    representative = await session.get(AssistantRepresentativeSettings, (tenant_id, user_id))
    if organization is None or representative is None:
        return AssistantPolicy()
    ids = await session.scalars(select(AssistantRepresentativeCapability.capability_id).where(
        AssistantRepresentativeCapability.tenant_id == tenant_id,
        AssistantRepresentativeCapability.user_id == user_id,
    ))
    return AssistantPolicy(
        organization_enabled=organization.enabled,
        representative_enabled=representative.enabled,
        enabled_capabilities=frozenset(ids),
    )
