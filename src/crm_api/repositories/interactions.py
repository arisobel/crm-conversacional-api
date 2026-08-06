"""Leitura e escrita da projeção de interações.

A timeline é sempre alcançada **pelo cliente**, que por sua vez passa pelo
`PortfolioScope` na camada de serviço. Não existe consulta de interação por id
solto: ela permitiria enumerar a conversa de carteiras alheias.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.interaction import CustomerInteraction


class InteractionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def add(self, interaction: CustomerInteraction) -> None:
        self._session.add(interaction)

    async def resolve_contact(
        self, tenant_id: uuid.UUID, phone: str
    ) -> tuple[CustomerContact, Customer] | None:
        """Localiza o contato pelo telefone, ativo ou não.

        Diferente de `CustomerRepository.get_active_by_whatsapp`, que serve à
        consulta comercial: desativar um contato encerra o atendimento por ele,
        mas não deve fazer o CRM perder o registro do que ele mandou.
        """
        result = await self._session.execute(
            select(CustomerContact, Customer)
            .join(Customer, Customer.id == CustomerContact.customer_id)
            .where(
                CustomerContact.tenant_id == tenant_id,
                CustomerContact.whatsapp_e164 == phone,
            )
        )
        return result.tuples().first()

    async def existing_refs(
        self, tenant_id: uuid.UUID, source: str, refs: Sequence[str]
    ) -> set[str]:
        if not refs:
            return set()
        return set(
            await self._session.scalars(
                select(CustomerInteraction.external_ref).where(
                    CustomerInteraction.tenant_id == tenant_id,
                    CustomerInteraction.source == source,
                    CustomerInteraction.external_ref.in_(list(refs)),
                )
            )
        )

    def _timeline(self, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Select:
        return select(CustomerInteraction).where(
            CustomerInteraction.tenant_id == tenant_id,
            CustomerInteraction.customer_id == customer_id,
        )

    async def count_timeline(self, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> int:
        statement = self._timeline(tenant_id, customer_id).with_only_columns(
            func.count(CustomerInteraction.id)
        )
        return await self._session.scalar(statement.order_by(None)) or 0

    async def list_timeline(
        self, tenant_id: uuid.UUID, customer_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[CustomerInteraction]:
        statement = (
            self._timeline(tenant_id, customer_id)
            # `id` desempata: dois eventos no mesmo instante existem, e sem o
            # segundo critério a paginação repetiria ou puliria linhas.
            .order_by(CustomerInteraction.occurred_at.desc(), CustomerInteraction.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await self._session.scalars(statement))

    async def last_interaction_map(
        self, tenant_id: uuid.UUID, customer_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, datetime]:
        """Data da última interação de cada cliente da página exibida.

        Uma consulta agregada em vez de uma coluna denormalizada em `customers`:
        a projeção é append-only e o índice `(customer_id, occurred_at)` já
        atende, então não vale manter um contador sincronizado.
        """
        if not customer_ids:
            return {}
        result = await self._session.execute(
            select(
                CustomerInteraction.customer_id,
                func.max(CustomerInteraction.occurred_at),
            )
            .where(
                CustomerInteraction.tenant_id == tenant_id,
                CustomerInteraction.customer_id.in_(list(customer_ids)),
            )
            .group_by(CustomerInteraction.customer_id)
        )
        return {customer_id: quando for customer_id, quando in result.all()}

    async def delete_before(self, tenant_id: uuid.UUID, cutoff: datetime) -> int:
        result = await self._session.execute(
            delete(CustomerInteraction).where(
                CustomerInteraction.tenant_id == tenant_id,
                CustomerInteraction.occurred_at < cutoff,
            )
        )
        return result.rowcount or 0
