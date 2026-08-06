"""Leitura e escrita do preço vigente por competência."""

import uuid
from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.pricing import PriceEntry, PriceEntryRevision

_ItemRow = tuple[PriceEntry, Product, ProductFamily]


class PriceEntryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def latest_month(self, tenant_id: uuid.UUID, *, at: date) -> date | None:
        """Competência aplicável: a mais recente que não seja futura.

        Publicar o mês seguinte com antecedência não pode antecipar o preço; a
        competência só passa a valer quando o mês chega.
        """
        return await self._session.scalar(
            select(PriceEntry.reference_month)
            .where(
                PriceEntry.tenant_id == tenant_id,
                PriceEntry.reference_month <= at.replace(day=1),
            )
            .order_by(PriceEntry.reference_month.desc())
            .limit(1)
        )

    async def list_months(self, tenant_id: uuid.UUID, *, limit: int = 24) -> list[date]:
        """Competências que já têm preço publicado, da mais recente para trás."""
        return list(
            await self._session.scalars(
                select(PriceEntry.reference_month)
                .where(PriceEntry.tenant_id == tenant_id)
                .group_by(PriceEntry.reference_month)
                .order_by(PriceEntry.reference_month.desc())
                .limit(limit)
            )
        )

    def _items_query(self, tenant_id: uuid.UUID, month: date) -> Select[_ItemRow]:
        return (
            select(PriceEntry, Product, ProductFamily)
            .join(Product, Product.id == PriceEntry.product_id)
            .join(ProductFamily, ProductFamily.id == Product.family_id)
            .where(
                PriceEntry.tenant_id == tenant_id,
                PriceEntry.reference_month == month,
                Product.active.is_(True),
                ProductFamily.active.is_(True),
            )
            .order_by(
                ProductFamily.display_order,
                PriceEntry.display_order,
                Product.commercial_name,
                Product.sku,
            )
        )

    async def list_items(self, tenant_id: uuid.UUID, month: date) -> list[_ItemRow]:
        result = await self._session.execute(self._items_query(tenant_id, month))
        return list(result.tuples())

    async def list_items_for_products(
        self, tenant_id: uuid.UUID, month: date, product_ids: list[uuid.UUID]
    ) -> list[_ItemRow]:
        if not product_ids:
            return []
        statement = self._items_query(tenant_id, month).where(
            PriceEntry.product_id.in_(product_ids)
        )
        result = await self._session.execute(statement)
        return list(result.tuples())

    async def get(
        self, tenant_id: uuid.UUID, month: date, product_id: uuid.UUID
    ) -> PriceEntry | None:
        return await self._session.scalar(
            select(PriceEntry).where(
                PriceEntry.tenant_id == tenant_id,
                PriceEntry.reference_month == month,
                PriceEntry.product_id == product_id,
            )
        )

    async def list_revisions(
        self, tenant_id: uuid.UUID, month: date, product_id: uuid.UUID | None = None
    ) -> list[PriceEntryRevision]:
        statement = select(PriceEntryRevision).where(
            PriceEntryRevision.tenant_id == tenant_id,
            PriceEntryRevision.reference_month == month,
        )
        if product_id is not None:
            statement = statement.where(PriceEntryRevision.product_id == product_id)
        return list(
            await self._session.scalars(statement.order_by(PriceEntryRevision.changed_at.desc()))
        )

    async def list_revisions_with_product(
        self, tenant_id: uuid.UUID, month: date, *, limit: int = 200
    ) -> list[tuple[PriceEntryRevision, Product]]:
        """Revisões da competência com o produto, para exibição.

        A revisão guarda `product_id`; a tela precisa do SKU e do nome
        comercial, e buscá-los uma vez por linha renderizada seria N+1.
        """
        result = await self._session.execute(
            select(PriceEntryRevision, Product)
            .join(Product, Product.id == PriceEntryRevision.product_id)
            .where(
                PriceEntryRevision.tenant_id == tenant_id,
                PriceEntryRevision.reference_month == month,
            )
            .order_by(PriceEntryRevision.changed_at.desc())
            .limit(limit)
        )
        return list(result.tuples())

    def add(self, entity: PriceEntry | PriceEntryRevision) -> None:
        self._session.add(entity)
