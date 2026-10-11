"""Decisão de atendimento por carteira na linha do representante.

Na linha Coexistence o robô só fala com cliente cuja conta pertence ao dono da
linha. Todo o resto — contato de outro representante, desconhecido, usuário
interno, cadastro ambíguo — fica fora do escopo, e o representante atende à mão
pelo app. A decisão é tomada aqui a cada mensagem, sem cache, para que a troca
de titular valha já na mensagem seguinte e sirva de corte de emergência.

O que este módulo responde é **se o robô atende**. O que a pessoa pode fazer
continua com o manifesto (`whatsapp_actor`), consultado só depois de um ALLOW.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.core.phone import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import User, UserRole
from crm_api.models.whatsapp_connection import RepresentativeWhatsappConnection
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.users import UserRepository
from crm_api.repositories.whatsapp_connections import WhatsappConnectionRepository
from crm_api.schemas.whatsapp_authorization import (
    AuthorizationDecisionRequest,
    Decision,
    DecisionReason,
)


@dataclass(frozen=True)
class AuthorizationOutcome:
    decision: Decision
    reason: DecisionReason
    customer_public_ref: str | None = None
    contact_public_ref: str | None = None
    connection_id: uuid.UUID | None = None


def _deny(
    reason: DecisionReason, connection: RepresentativeWhatsappConnection | None = None
) -> AuthorizationOutcome:
    return AuthorizationOutcome(
        decision=Decision.DENY,
        reason=reason,
        connection_id=connection.id if connection else None,
    )


def _phone_suffix(phone: str) -> str:
    # O suficiente para a operação reconhecer o caso sem guardar o número de
    # quem não é cliente — a maior parte do que chega a uma linha pessoal.
    return f"***{phone[-4:]}" if len(phone) >= 4 else "***"


class PortfolioAuthorizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._connections = WhatsappConnectionRepository(session)
        self._audit = AuditRepository(session)

    async def decide(
        self, tenant_slug: str, request: AuthorizationDecisionRequest
    ) -> AuthorizationOutcome:
        tenant = await self._users.get_tenant(tenant_slug)
        outcome = (
            await self._evaluate(tenant.id, request)
            if tenant is not None
            else _deny(DecisionReason.LINE_UNKNOWN)
        )
        if outcome.decision is Decision.DENY:
            self._audit.record(
                action="WHATSAPP_AUTHORIZATION_DENIED",
                entity="representative_whatsapp_connections",
                tenant_id=tenant.id if tenant is not None else None,
                entity_id=outcome.connection_id,
                after={
                    "reason": outcome.reason.value,
                    "gateway_line_reference": request.gateway_line_reference,
                    "application_slug": request.application_slug,
                    "flow_slug": request.flow_slug,
                    "phone_suffix": _phone_suffix(request.phone_e164),
                },
                request_id=request.message_id,
            )
        return outcome

    async def _evaluate(
        self, tenant_id: uuid.UUID, request: AuthorizationDecisionRequest
    ) -> AuthorizationOutcome:
        # A ordem importa: a linha vem antes do remetente. Linha desconhecida
        # ou sem dono apto nega tudo, e nenhum dado de contato é consultado.
        connections = await self._connections.list_connected_by_line_reference(
            tenant_id, request.gateway_line_reference
        )
        if len(connections) != 1:
            return _deny(DecisionReason.LINE_UNKNOWN)
        connection = connections[0]

        line_owner = await self._users.get_in_tenant(tenant_id, connection.representative_user_id)
        # Papel conferido de novo: a conexão exigiu REPRESENTATIVE quando foi
        # criada, mas o papel pode ter mudado depois.
        if (
            line_owner is None
            or not line_owner.active
            or line_owner.role is not UserRole.REPRESENTATIVE
        ):
            return _deny(DecisionReason.LINE_OWNER_INACTIVE, connection)

        try:
            phone = normalize_whatsapp_e164(request.phone_e164)
        except InvalidWhatsappNumber:
            return _deny(DecisionReason.CONTACT_NOT_FOUND, connection)

        internal_user = await self._session.scalar(
            select(User.id).where(
                User.tenant_id == tenant_id,
                User.whatsapp_e164 == phone,
                User.active.is_(True),
            )
        )
        # Todos os contatos com o telefone, ativos ou não, e não o primeiro:
        # o banco já impede duplicidade, mas escolher um dos lados de um
        # cadastro ambíguo seria conceder atendimento por conta própria.
        matches = (
            (
                await self._session.execute(
                    select(CustomerContact, Customer)
                    .join(Customer, Customer.id == CustomerContact.customer_id)
                    .where(
                        CustomerContact.tenant_id == tenant_id,
                        CustomerContact.whatsapp_e164 == phone,
                    )
                )
            )
            .tuples()
            .all()
        )

        if internal_user is not None:
            if any(contact.active and customer.active for contact, customer in matches):
                return _deny(DecisionReason.AMBIGUOUS_PHONE, connection)
            return _deny(DecisionReason.INTERNAL_USER, connection)
        if not matches:
            return _deny(DecisionReason.CONTACT_NOT_FOUND, connection)
        if len(matches) > 1:
            return _deny(DecisionReason.AMBIGUOUS_PHONE, connection)

        contact, customer = matches[0]
        if not customer.active:
            return _deny(DecisionReason.CUSTOMER_INACTIVE, connection)
        if not contact.active:
            return _deny(DecisionReason.CONTACT_NOT_FOUND, connection)
        if customer.owner_user_id is None:
            return _deny(DecisionReason.CUSTOMER_WITHOUT_OWNER, connection)
        if customer.owner_user_id != line_owner.id:
            return _deny(DecisionReason.OWNER_MISMATCH, connection)

        return AuthorizationOutcome(
            decision=Decision.ALLOW,
            reason=DecisionReason.AUTHORIZED,
            # `Customer` não tem `public_ref`; o id já é exposto ao Gateway por
            # `/customers/by-whatsapp`, então não é dado novo do outro lado.
            customer_public_ref=str(customer.id),
            contact_public_ref=contact.public_ref,
            connection_id=connection.id,
        )
