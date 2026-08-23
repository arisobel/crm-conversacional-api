"""Catálogo de artigos e o lote de rascunho que recebe inclusões pelo portal."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import (
    CustomerPreferredProduct,
    Product,
    ProductFamily,
    ProductGroup,
    ProductGroupMember,
)
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceEntry,
    PriceList,
    PriceListItem,
    PriceListStatus,
)


@dataclass(frozen=True)
class ProductFilters:
    """Recortes da tela de catálogo. Nenhum deles altera o escopo de tenant."""

    search: str | None = None
    family_id: uuid.UUID | None = None
    # `None` traz ativos e inativos; a tela precisa dos dois para reativar.
    active: bool | None = True
    # Só artigos sem preço na competência — é como se acha o que ficou de fora
    # da tabela do mês.
    without_price: bool = False


@dataclass(frozen=True)
class ProductRow:
    """Linha da lista: o artigo, sua família e o preço da competência."""

    product: Product
    family: ProductFamily
    base_price: Decimal | None
    availability: AvailabilityStatus | None
    preferred_by: int
    # Se alguma competência já publicou este artigo — em qualquer mês, não só no
    # corrente. É o que trava o SKU na edição.
    has_published_price: bool


class CatalogRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    # ------------------------------------------------------------- famílias

    async def list_families(
        self, tenant_id: uuid.UUID, *, active: bool | None = True
    ) -> list[ProductFamily]:
        statement = select(ProductFamily).where(ProductFamily.tenant_id == tenant_id)
        if active is not None:
            statement = statement.where(ProductFamily.active.is_(active))
        return list(
            await self._session.scalars(
                statement.order_by(ProductFamily.display_order, ProductFamily.name)
            )
        )

    async def count_products_by_family(self, tenant_id: uuid.UUID) -> dict[uuid.UUID, int]:
        result = await self._session.execute(
            select(Product.family_id, func.count(Product.id))
            .where(Product.tenant_id == tenant_id, Product.active.is_(True))
            .group_by(Product.family_id)
        )
        return {family_id: total for family_id, total in result.all()}

    async def family_name_taken(
        self, tenant_id: uuid.UUID, name: str, *, excluding: uuid.UUID | None = None
    ) -> bool:
        statement = select(ProductFamily.id).where(
            ProductFamily.tenant_id == tenant_id, ProductFamily.name == name
        )
        if excluding is not None:
            statement = statement.where(ProductFamily.id != excluding)
        return await self._session.scalar(statement) is not None

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

    async def sku_exists(
        self, tenant_id: uuid.UUID, sku: str, *, excluding: uuid.UUID | None = None
    ) -> bool:
        """Inclui o produto inativo: o SKU é único no banco por tenant.

        Um SKU desativado ainda ocupa a chave, e deixar a tela tentar gravar
        devolveria violação de índice no lugar de "já existe esse SKU".
        """
        statement = select(Product.id).where(
            Product.tenant_id == tenant_id, Product.sku == sku
        )
        if excluding is not None:
            statement = statement.where(Product.id != excluding)
        return await self._session.scalar(statement) is not None

    async def get_product(self, tenant_id: uuid.UUID, product_id: uuid.UUID) -> Product | None:
        return await self._session.scalar(
            select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id)
        )

    async def has_published_price(self, tenant_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        """Se o artigo já foi publicado alguma vez, o SKU virou chave externa.

        Não é chave no sentido do banco: é a coluna pela qual a planilha do mês
        reencontra o artigo. Trocá-la depois faria a próxima importação criar um
        segundo artigo com o SKU antigo, e ninguém veria o catálogo duplicar.
        """
        found = await self._session.scalar(
            select(PriceEntry.id).where(
                PriceEntry.tenant_id == tenant_id, PriceEntry.product_id == product_id
            )
        )
        return found is not None

    async def list_products(
        self, tenant_id: uuid.UUID, filters: ProductFilters, *, month: date | None = None
    ) -> list[ProductRow]:
        """Artigos com família, preço da competência e quantos clientes os preferem.

        O preço entra por `outerjoin`: artigo sem entrada na competência é
        exatamente o caso que a tela precisa mostrar, não esconder.
        """
        preferidos = (
            select(
                CustomerPreferredProduct.product_id.label("product_id"),
                func.count(CustomerPreferredProduct.id).label("total"),
            )
            .where(CustomerPreferredProduct.active.is_(True))
            .group_by(CustomerPreferredProduct.product_id)
            .subquery()
        )

        publicados = (
            select(PriceEntry.product_id.label("product_id"))
            .where(PriceEntry.tenant_id == tenant_id)
            .group_by(PriceEntry.product_id)
            .subquery()
        )

        statement = (
            select(
                Product,
                ProductFamily,
                PriceEntry.base_price,
                PriceEntry.availability,
                func.coalesce(preferidos.c.total, 0),
                publicados.c.product_id.is_not(None),
            )
            .join(ProductFamily, ProductFamily.id == Product.family_id)
            .outerjoin(
                PriceEntry,
                (PriceEntry.product_id == Product.id)
                & (PriceEntry.reference_month == month)
                & (PriceEntry.tenant_id == tenant_id),
            )
            .outerjoin(preferidos, preferidos.c.product_id == Product.id)
            .outerjoin(publicados, publicados.c.product_id == Product.id)
            .where(Product.tenant_id == tenant_id)
            .order_by(ProductFamily.display_order, Product.commercial_name, Product.sku)
        )

        if filters.active is not None:
            statement = statement.where(Product.active.is_(filters.active))
        if filters.family_id is not None:
            statement = statement.where(Product.family_id == filters.family_id)
        if filters.without_price:
            statement = statement.where(PriceEntry.id.is_(None))
        if filters.search:
            alvo = f"%{filters.search.strip().lower()}%"
            statement = statement.where(
                or_(
                    func.lower(Product.sku).like(alvo),
                    func.lower(Product.commercial_name).like(alvo),
                    func.lower(func.coalesce(Product.specification, "")).like(alvo),
                )
            )

        result = await self._session.execute(statement)
        return [
            ProductRow(
                product=produto,
                family=familia,
                base_price=preco,
                availability=disponibilidade,
                preferred_by=total,
                has_published_price=bool(publicado),
            )
            for produto, familia, preco, disponibilidade, total, publicado in result.tuples()
        ]

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

    # ------------------------------------------------- grupos de artigo

    async def list_groups(
        self, tenant_id: uuid.UUID, *, active: bool | None = True
    ) -> list[ProductGroup]:
        statement = select(ProductGroup).where(ProductGroup.tenant_id == tenant_id)
        if active is not None:
            statement = statement.where(ProductGroup.active.is_(active))
        return list(
            await self._session.scalars(statement.order_by(ProductGroup.normalized_name))
        )

    async def find_group_by_name(
        self, tenant_id: uuid.UUID, normalized: str
    ) -> ProductGroup | None:
        """Procura pelo nome canônico, não pelo digitado.

        É o que faz "Poliéster" reencontrar o "poliester" que já existe, em vez
        de criar um irmão que divide o público do disparo ao meio.
        """
        return await self._session.scalar(
            select(ProductGroup).where(
                ProductGroup.tenant_id == tenant_id,
                ProductGroup.normalized_name == normalized,
            )
        )

    async def get_group(
        self, tenant_id: uuid.UUID, group_id: uuid.UUID
    ) -> ProductGroup | None:
        return await self._session.scalar(
            select(ProductGroup).where(
                ProductGroup.tenant_id == tenant_id, ProductGroup.id == group_id
            )
        )

    async def count_products_by_group(self, tenant_id: uuid.UUID) -> dict[uuid.UUID, int]:
        result = await self._session.execute(
            select(ProductGroupMember.group_id, func.count(ProductGroupMember.id))
            .where(ProductGroupMember.tenant_id == tenant_id)
            .group_by(ProductGroupMember.group_id)
        )
        return {group_id: quantos for group_id, quantos in result.all()}

    async def groups_of_products(
        self, tenant_id: uuid.UUID, product_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[ProductGroup]]:
        """Grupos de cada artigo da página exibida, numa consulta só."""
        if not product_ids:
            return {}
        result = await self._session.execute(
            select(ProductGroupMember.product_id, ProductGroup)
            .join(ProductGroup, ProductGroup.id == ProductGroupMember.group_id)
            .where(
                ProductGroupMember.tenant_id == tenant_id,
                ProductGroupMember.product_id.in_(product_ids),
            )
            .order_by(ProductGroup.normalized_name)
        )
        por_artigo: dict[uuid.UUID, list[ProductGroup]] = {}
        for product_id, grupo in result.tuples().all():
            por_artigo.setdefault(product_id, []).append(grupo)
        return por_artigo

    async def get_membership(
        self, tenant_id: uuid.UUID, group_id: uuid.UUID, product_id: uuid.UUID
    ) -> ProductGroupMember | None:
        return await self._session.scalar(
            select(ProductGroupMember).where(
                ProductGroupMember.tenant_id == tenant_id,
                ProductGroupMember.group_id == group_id,
                ProductGroupMember.product_id == product_id,
            )
        )

    async def remove_membership(self, membership: ProductGroupMember) -> None:
        await self._session.delete(membership)

    # ---------------------------------------------------------------- comum

    def add(
        self,
        entity: ProductFamily
        | Product
        | PriceList
        | PriceListItem
        | ProductGroup
        | ProductGroupMember,
    ) -> None:
        self._session.add(entity)

    async def flush(self) -> None:
        await self._session.flush()
