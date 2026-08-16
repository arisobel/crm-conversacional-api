"""Quem está falando pelo WhatsApp, do ponto de vista do CRM.

O Gateway decide **se atende**; este módulo decide **o que a pessoa pode fazer**
(ADR-022). As duas decisões vivem em sistemas diferentes de propósito, e é por
isso que a resolução aqui não consulta o roster: ela lê o cadastro.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import User


class ActorRole(StrEnum):
    """O papel como o Gateway o vê. Texto livre no contrato; fechado aqui."""

    REPRESENTATIVE = "representante"
    CUSTOMER = "cliente"


@dataclass(frozen=True)
class WhatsappActor:
    role: ActorRole
    public_ref: str
    user_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None


class ActorNotFound(Exception):
    """Telefone que não é contato de cliente nem usuário do portal.

    Não deveria acontecer: o Gateway só encaminha quem ele autorizou. Quando
    acontece, é sinal de roster defasado ou de número digitado à mão no painel
    sem cadastro correspondente aqui — o segundo caso é a consequência aceita da
    D5, e a tela de conferência existe para expô-lo antes.
    """


class AmbiguousActor(Exception):
    """O mesmo telefone é contato de cliente **e** usuário do portal.

    Falha fechada. É a rota de escalação mais barata do desenho, e o cadastro
    já a recusa nas duas bordas de escrita desde a W1 — chegar aqui significa
    dado anterior a ela, e escolher um dos lados seria conceder alçada por
    conta própria.
    """


class WhatsappActorResolver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, tenant_id: uuid.UUID, phone: str) -> WhatsappActor:
        """Resolve o telefone **já canônico** ao ator dono dele.

        Só entidades ativas: um representante desativado no portal não recebe
        capacidade nenhuma, mesmo que a autorização dele sobreviva no painel do
        Gateway. É o mais perto que o CRM chega de desligar o acesso de quem não
        controla o próprio roster.
        """
        usuario = await self._session.scalar(
            select(User).where(
                User.tenant_id == tenant_id,
                User.whatsapp_e164 == phone,
                User.active.is_(True),
            )
        )
        contato = (
            await self._session.execute(
                select(CustomerContact, Customer)
                .join(Customer, Customer.id == CustomerContact.customer_id)
                .where(
                    CustomerContact.tenant_id == tenant_id,
                    CustomerContact.whatsapp_e164 == phone,
                    CustomerContact.active.is_(True),
                    Customer.active.is_(True),
                )
            )
        ).tuples().first()

        if usuario is not None and contato is not None:
            raise AmbiguousActor("phone belongs to both a portal user and a customer contact")

        if usuario is not None:
            return WhatsappActor(
                role=ActorRole.REPRESENTATIVE,
                public_ref=usuario.public_ref,
                user_id=usuario.id,
            )

        if contato is not None:
            registro, cliente = contato
            return WhatsappActor(
                role=ActorRole.CUSTOMER,
                public_ref=registro.public_ref,
                customer_id=cliente.id,
                contact_id=registro.id,
            )

        raise ActorNotFound("no active portal user or customer contact matches this phone")
