from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.pricing import PriceList, PriceListItem, PriceListStatus


class PriceListRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_current(self, tenant_id: UUID, at: datetime) -> PriceList | None:
        statement = (
            select(PriceList)
            .where(
                PriceList.tenant_id == tenant_id,
                PriceList.status == PriceListStatus.ACTIVE,
                PriceList.valid_from <= at,
                or_(PriceList.valid_until.is_(None), PriceList.valid_until > at),
            )
            .order_by(PriceList.valid_from.desc(), PriceList.created_at.desc())
            .limit(1)
        )
        return await self._session.scalar(statement)

    def _items_query(
        self, price_list_id: UUID
    ) -> Select[tuple[PriceListItem, Product, ProductFamily]]:
        return (
            select(PriceListItem, Product, ProductFamily)
            .join(Product, Product.id == PriceListItem.product_id)
            .join(ProductFamily, ProductFamily.id == Product.family_id)
            .where(
                PriceListItem.price_list_id == price_list_id,
                Product.active.is_(True),
                ProductFamily.active.is_(True),
            )
            .order_by(
                ProductFamily.display_order,
                PriceListItem.display_order,
                Product.commercial_name,
                Product.sku,
            )
        )

    async def list_items(
        self, price_list_id: UUID
    ) -> list[tuple[PriceListItem, Product, ProductFamily]]:
        result = await self._session.execute(self._items_query(price_list_id))
        return list(result.tuples())
