from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer import Customer, Tenant
from crm_api.models.customer_contact import CustomerContact


class CustomerRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def _active_contact_query(
        self, tenant_slug: str, phone: str
    ) -> Select[tuple[CustomerContact, Customer]]:
        return (
            select(CustomerContact, Customer)
            .join(Customer, Customer.id == CustomerContact.customer_id)
            .join(Tenant, Tenant.id == CustomerContact.tenant_id)
            .where(
                Tenant.slug == tenant_slug,
                Tenant.active.is_(True),
                CustomerContact.whatsapp_e164 == phone,
                CustomerContact.active.is_(True),
                Customer.active.is_(True),
            )
        )

    async def get_active_by_whatsapp(
        self, tenant_slug: str, phone: str
    ) -> tuple[CustomerContact, Customer] | None:
        result = await self._session.execute(self._active_contact_query(tenant_slug, phone))
        return result.one_or_none()

    async def list_active_whatsapp(self, tenant_slug: str) -> list[str]:
        """Telefones que podem conversar pelo WhatsApp, em ordem estável.

        Só o telefone: o Gateway precisa decidir se atende, não saber de quem é.
        A ordenação é o que torna o `etag` comparável entre duas leituras.
        """
        result = await self._session.scalars(
            select(CustomerContact.whatsapp_e164)
            .join(Customer, Customer.id == CustomerContact.customer_id)
            .join(Tenant, Tenant.id == CustomerContact.tenant_id)
            .where(
                Tenant.slug == tenant_slug,
                Tenant.active.is_(True),
                CustomerContact.active.is_(True),
                Customer.active.is_(True),
            )
            .order_by(CustomerContact.whatsapp_e164)
        )
        return list(result)

    async def get_tenant(self, tenant_slug: str) -> Tenant | None:
        """Tenant ativo da implantação.

        A conversão de ICMS precisa da UF de origem, que vive aqui; sem ela o
        cálculo falha de propósito em vez de assumir uma praça.
        """
        return await self._session.scalar(
            select(Tenant).where(Tenant.slug == tenant_slug, Tenant.active.is_(True))
        )
