"""Leitura e escrita da projeção de campanhas de WhatsApp.

O escopo é aplicado **aqui**, como no `CustomerPortfolioRepository`: um
representante alcança apenas campanhas cujo responsável comercial congelado é
ele. Filtrar na rota deixaria a próxima rota livre para esquecer — e a rota de
campanhas ainda nem existe (F6.3), o que torna o repositório o único lugar
onde a regra pode nascer.
"""

import uuid
from contextlib import AbstractAsyncContextManager

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.whatsapp_campaign import (
    CampaignStatus,
    WhatsappCampaign,
    WhatsappCampaignRecipient,
)


class WhatsappCampaignRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def add(self, entity: WhatsappCampaign | WhatsappCampaignRecipient) -> None:
        self._session.add(entity)

    async def flush(self) -> None:
        await self._session.flush()

    def savepoint(self) -> AbstractAsyncContextManager:
        """`SAVEPOINT` para isolar a inserção que pode colidir na idempotência.

        Sem ele, a violação de unicidade aborta a transação inteira e não sobra
        sessão utilizável para reler a campanha que venceu a corrida.
        """
        return self._session.begin_nested()

    # ------------------------------------------------------------- campanhas

    async def by_idempotency_key(
        self, tenant_id: uuid.UUID, idempotency_key: str
    ) -> WhatsappCampaign | None:
        """A campanha já criada por este comando, em qualquer estado.

        Uma reentrega depois de o rascunho ser cancelado — ou, no futuro,
        confirmado — não pode abrir uma segunda campanha.
        """
        return await self._session.scalar(
            select(WhatsappCampaign).where(
                WhatsappCampaign.tenant_id == tenant_id,
                WhatsappCampaign.idempotency_key == idempotency_key,
            )
        )

    async def get(
        self,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        *,
        representative_user_id: uuid.UUID | None = None,
    ) -> WhatsappCampaign | None:
        """Uma campanha, dentro do alcance de quem pede.

        `representative_user_id` presente restringe ao responsável congelado —
        é o recorte do `REPRESENTATIVE`. Nulo significa "todo o tenant" e só é
        produzido para `ADMIN` e `MANAGER`, como no `PortfolioScope`.
        """
        statement = select(WhatsappCampaign).where(
            WhatsappCampaign.tenant_id == tenant_id,
            WhatsappCampaign.id == campaign_id,
        )
        if representative_user_id is not None:
            statement = statement.where(
                WhatsappCampaign.representative_user_id == representative_user_id
            )
        return await self._session.scalar(statement)

    def _scoped(
        self,
        tenant_id: uuid.UUID,
        *,
        representative_user_id: uuid.UUID | None,
        status: CampaignStatus | None,
    ) -> Select:
        statement = select(WhatsappCampaign).where(WhatsappCampaign.tenant_id == tenant_id)
        if representative_user_id is not None:
            statement = statement.where(
                WhatsappCampaign.representative_user_id == representative_user_id
            )
        if status is not None:
            statement = statement.where(WhatsappCampaign.status == status)
        return statement

    async def count(
        self,
        tenant_id: uuid.UUID,
        *,
        representative_user_id: uuid.UUID | None = None,
        status: CampaignStatus | None = None,
    ) -> int:
        statement = self._scoped(
            tenant_id, representative_user_id=representative_user_id, status=status
        )
        return await self._session.scalar(
            select(func.count()).select_from(statement.subquery())
        ) or 0

    # ---------------------------------------------------------- destinatários

    async def recipients(
        self, tenant_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> list[WhatsappCampaignRecipient]:
        """Os destinatários de uma campanha **já alcançada** pelo chamador.

        Não reaplica escopo: o serviço só chega aqui depois de `get` devolver a
        campanha dentro do alcance — reaplicar exigiria repetir a regra em dois
        lugares que poderiam divergir.
        """
        return list(
            await self._session.scalars(
                select(WhatsappCampaignRecipient)
                .where(
                    WhatsappCampaignRecipient.tenant_id == tenant_id,
                    WhatsappCampaignRecipient.campaign_id == campaign_id,
                )
                .order_by(WhatsappCampaignRecipient.created_at)
            )
        )

    async def campaigns_of_customer(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        representative_user_id: uuid.UUID | None = None,
        limit: int = 20,
    ) -> list[tuple[WhatsappCampaign, WhatsappCampaignRecipient]]:
        """As campanhas de que este cliente participou, para a ficha dele.

        O escopo é o mesmo da lista: um representante só vê as campanhas de que
        é responsável, mesmo abrindo a ficha de um cliente seu. Uma campanha de
        outra carteira que tenha alcançado este cliente não aparece — quem a
        criou é que responde por ela.
        """
        statement = (
            select(WhatsappCampaign, WhatsappCampaignRecipient)
            .join(
                WhatsappCampaignRecipient,
                WhatsappCampaignRecipient.campaign_id == WhatsappCampaign.id,
            )
            .where(
                WhatsappCampaign.tenant_id == tenant_id,
                WhatsappCampaignRecipient.customer_id == customer_id,
            )
            .order_by(WhatsappCampaign.created_at.desc())
            .limit(limit)
        )
        if representative_user_id is not None:
            statement = statement.where(
                WhatsappCampaign.representative_user_id == representative_user_id
            )
        return list((await self._session.execute(statement)).tuples().all())

    # ------------------------------------------------- consulta de referência

    async def customers_by_ids(
        self, tenant_id: uuid.UUID, customer_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Customer]:
        """Clientes do tenant, indexados por id, para validação de rascunho.

        O filtro de tenant mora aqui de propósito: um id de outro tenant sai do
        dicionário e o serviço o trata como inexistente, sem revelar que existe
        em outro lugar.
        """
        if not customer_ids:
            return {}
        rows = await self._session.scalars(
            select(Customer).where(
                Customer.tenant_id == tenant_id, Customer.id.in_(customer_ids)
            )
        )
        return {row.id: row for row in rows}

    async def contacts_by_ids(
        self, tenant_id: uuid.UUID, contact_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, CustomerContact]:
        if not contact_ids:
            return {}
        rows = await self._session.scalars(
            select(CustomerContact).where(
                CustomerContact.tenant_id == tenant_id,
                CustomerContact.id.in_(contact_ids),
            )
        )
        return {row.id: row for row in rows}

    # Definido por último de propósito: um método chamado `list` sombreia o
    # builtin nas anotações que vêm depois dele no corpo da classe.
    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        representative_user_id: uuid.UUID | None = None,
        status: CampaignStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WhatsappCampaign]:
        statement = (
            self._scoped(
                tenant_id,
                representative_user_id=representative_user_id,
                status=status,
            )
            .order_by(WhatsappCampaign.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await self._session.scalars(statement))
