"""Escrita e leitura do cadastro comercial: cliente, contatos e localidades.

Contatos e localidades são sempre alcançados **pelo cliente**, que por sua vez
passa pelo `PortfolioScope`. Não existe rota que leia um contato por id solto:
isso permitiria enumerar contatos de carteiras alheias.
"""

import uuid

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer import Customer, CustomerLocation
from crm_api.models.customer_contact import CustomerContact


class CustomerAdminRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def add(self, entity: Customer | CustomerContact | CustomerLocation) -> None:
        self._session.add(entity)

    async def flush(self) -> None:
        await self._session.flush()

    async def document_exists(
        self, tenant_id: uuid.UUID, document_number: str, *, excluding: uuid.UUID | None = None
    ) -> bool:
        statement = select(Customer.id).where(
            Customer.tenant_id == tenant_id, Customer.document_number == document_number
        )
        if excluding is not None:
            statement = statement.where(Customer.id != excluding)
        return await self._session.scalar(statement) is not None

    async def whatsapp_exists(
        self, tenant_id: uuid.UUID, phone: str, *, excluding: uuid.UUID | None = None
    ) -> bool:
        statement = select(CustomerContact.id).where(
            CustomerContact.tenant_id == tenant_id, CustomerContact.whatsapp_e164 == phone
        )
        if excluding is not None:
            statement = statement.where(CustomerContact.id != excluding)
        return await self._session.scalar(statement) is not None

    def _contacts(self, customer_id: uuid.UUID) -> Select[tuple[CustomerContact]]:
        return select(CustomerContact).where(CustomerContact.customer_id == customer_id)

    async def list_contacts(self, customer_id: uuid.UUID) -> list[CustomerContact]:
        statement = self._contacts(customer_id).order_by(
            CustomerContact.is_primary.desc(), CustomerContact.name
        )
        return list(await self._session.scalars(statement))

    async def get_contact(
        self, customer_id: uuid.UUID, contact_id: uuid.UUID
    ) -> CustomerContact | None:
        return await self._session.scalar(
            self._contacts(customer_id).where(CustomerContact.id == contact_id)
        )

    async def clear_primary_contact(
        self, customer_id: uuid.UUID, *, excluding: uuid.UUID | None = None
    ) -> None:
        """Desmarca o contato principal vigente.

        Roda antes de marcar o novo, na mesma transação: o índice parcial
        `ux_primary_contact_per_customer` recusaria dois principais ativos.
        """
        statement = update(CustomerContact).where(
            CustomerContact.customer_id == customer_id, CustomerContact.is_primary.is_(True)
        )
        if excluding is not None:
            statement = statement.where(CustomerContact.id != excluding)
        await self._session.execute(statement.values(is_primary=False))

    def _locations(self, customer_id: uuid.UUID) -> Select[tuple[CustomerLocation]]:
        return select(CustomerLocation).where(CustomerLocation.customer_id == customer_id)

    async def list_locations(self, customer_id: uuid.UUID) -> list[CustomerLocation]:
        statement = self._locations(customer_id).order_by(
            CustomerLocation.is_default.desc(), CustomerLocation.label
        )
        return list(await self._session.scalars(statement))

    async def get_location(
        self, customer_id: uuid.UUID, location_id: uuid.UUID
    ) -> CustomerLocation | None:
        return await self._session.scalar(
            self._locations(customer_id).where(CustomerLocation.id == location_id)
        )

    async def get_default_location(self, customer_id: uuid.UUID) -> CustomerLocation | None:
        return await self._session.scalar(
            self._locations(customer_id).where(
                CustomerLocation.is_default.is_(True), CustomerLocation.active.is_(True)
            )
        )

    async def clear_default_location(
        self, customer_id: uuid.UUID, *, excluding: uuid.UUID | None = None
    ) -> None:
        statement = update(CustomerLocation).where(
            CustomerLocation.customer_id == customer_id, CustomerLocation.is_default.is_(True)
        )
        if excluding is not None:
            statement = statement.where(CustomerLocation.id != excluding)
        await self._session.execute(statement.values(is_default=False))

    async def count_active_locations(
        self, customer_id: uuid.UUID, *, excluding: uuid.UUID | None = None
    ) -> int:
        statement = select(CustomerLocation.id).where(
            CustomerLocation.customer_id == customer_id, CustomerLocation.active.is_(True)
        )
        if excluding is not None:
            statement = statement.where(CustomerLocation.id != excluding)
        return len(list(await self._session.scalars(statement)))
