"""Catálogo de artigos e o lote de rascunho que recebe inclusões pelo portal."""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.pricing import PriceList, PriceListItem, PriceListStatus


class CatalogRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    # ------------------------------------------------------------- famílias

    async def list_families(self, tenant_id: uuid.UUID) -> list[ProductFamily]:
        return list(
            await self._session.scalars(
                select(ProductFamily)
                .where(ProductFamily.tenant_id == tenant_id, ProductFamily.active.is_(True))
                .order_by(ProductFamily.display_order, ProductFamily.name)
            )
        )

    async def get_family(
        self, tenant_id: uuid.UUID, family_id: uuid.UUID
    ) -> ProductFamily | None:
        return await self._session.scalar(
            select(ProductFamily).where(
                ProductFamily.tenant_id == tenant_id, ProductFamily.id == family_id
            )
        )

    async def find_family_by_name(self, tenant_id: uuid.UUID, name: str) -> ProductFamily | None:
        """Busca pelo nome exato, que é o que o banco torna único.

        Reaproveitar a família em vez de criar outra evita que "Rubberflex" e
        "Rubberflex " virem duas famílias — e a unicidade `(tenant, name)`
        rejeitaria a segunda de qualquer forma, com erro de banco em vez de
        mensagem de tela.
        """
        return await self._session.scalar(
            select(ProductFamily).where(
                ProductFamily.tenant_id == tenant_id, ProductFamily.name == name
            )
        )

    async def next_family_order(self, tenant_id: uuid.UUID) -> int:
        maior = await self._session.scalar(
            select(func.max(ProductFamily.display_order)).where(
                ProductFamily.tenant_id == tenant_id
            )
        )
        return (maior or 0) + 1

    # ------------------------------------------------------------- produtos

    async def sku_exists(self, tenant_id: uuid.UUID, sku: str) -> bool:
        """Inclui o produto inativo: o SKU é único no banco por tenant.

        Um SKU desativado ainda ocupa a chave, e deixar a tela tentar gravar
        devolveria violação de índice no lugar de "já existe esse SKU".
        """
        found = await self._session.scalar(
            select(Product.id).where(Product.tenant_id == tenant_id, Product.sku == sku)
        )
        return found is not None

    # ----------------------------------------------------- lote de rascunho

    async def find_draft_batch(
        self, tenant_id: uuid.UUID, reference_month: date, name: str
    ) -> PriceList | None:
        return await self._session.scalar(
            select(PriceList).where(
                PriceList.tenant_id == tenant_id,
                PriceList.reference_month == reference_month,
                PriceList.name == name,
                PriceList.status == PriceListStatus.DRAFT,
            )
        )

    async def free_batch_name(
        self, tenant_id: uuid.UUID, reference_month: date, base: str
    ) -> str:
        """Primeiro nome livre a partir de `base` na competência.

        Só sai do nome base quando o lote anterior já foi publicado; o sufixo
        existe para não bater na unicidade `(tenant, nome, competência)`.
        """
        taken = set(
            await self._session.scalars(
                select(PriceList.name).where(
                    PriceList.tenant_id == tenant_id,
                    PriceList.reference_month == reference_month,
                    PriceList.name.startswith(base),
                )
            )
        )
        if base not in taken:
            return base
        suffix = 2
        while f"{base} ({suffix})" in taken:
            suffix += 1
        return f"{base} ({suffix})"

    async def count_batch_items(self, price_list_id: uuid.UUID) -> int:
        return (
            await self._session.scalar(
                select(func.count(PriceListItem.id)).where(
                    PriceListItem.price_list_id == price_list_id
                )
            )
            or 0
        )

    # ---------------------------------------------------------------- comum

    def add(self, entity: ProductFamily | Product | PriceList | PriceListItem) -> None:
        self._session.add(entity)

    async def flush(self) -> None:
        await self._session.flush()
