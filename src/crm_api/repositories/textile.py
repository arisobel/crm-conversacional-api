"""Leitura e escrita da camada têxtil.

Toda consulta é fechada por `tenant_id`. A composição não tem leitura por id
solto porque ninguém precisa dela: ela é sempre alcançada pelo artigo ou pela
fibra.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import Product
from crm_api.models.textile import Fiber, ProductComposition


class TextileRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    # ----------------------------------------------------------------- fibra

    def add(self, entity: Fiber | ProductComposition) -> None:
        self._session.add(entity)

    async def flush(self) -> None:
        await self._session.flush()

    async def list_fibers(
        self, tenant_id: uuid.UUID, *, active: bool | None = True
    ) -> list[Fiber]:
        statement = select(Fiber).where(Fiber.tenant_id == tenant_id)
        if active is not None:
            statement = statement.where(Fiber.active.is_(active))
        return list(await self._session.scalars(statement.order_by(Fiber.code)))

    async def find_fiber_by_code(self, tenant_id: uuid.UUID, code: str) -> Fiber | None:
        """Casa pela sigla em caixa alta — é assim que a planilha do setor traz."""
        return await self._session.scalar(
            select(Fiber).where(Fiber.tenant_id == tenant_id, Fiber.code == code.strip().upper())
        )

    async def fibers_by_code(
        self, tenant_id: uuid.UUID, codes: Sequence[str]
    ) -> dict[str, Fiber]:
        """Resolve várias siglas de uma vez, para o CSV não consultar por linha."""
        canonicos = {code.strip().upper() for code in codes if code.strip()}
        if not canonicos:
            return {}
        encontradas = await self._session.scalars(
            select(Fiber).where(Fiber.tenant_id == tenant_id, Fiber.code.in_(canonicos))
        )
        return {fibra.code: fibra for fibra in encontradas}

    # ------------------------------------------------------------ composição

    async def composition_of(
        self, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> list[tuple[ProductComposition, Fiber]]:
        result = await self._session.execute(
            select(ProductComposition, Fiber)
            .join(Fiber, Fiber.id == ProductComposition.fiber_id)
            .where(
                ProductComposition.tenant_id == tenant_id,
                ProductComposition.product_id == product_id,
            )
            .order_by(ProductComposition.percent.desc(), Fiber.code)
        )
        return list(result.tuples().all())

    async def clear_composition(self, tenant_id: uuid.UUID, product_id: uuid.UUID) -> int:
        """Apaga a composição inteira do artigo.

        `set_composition` substitui em vez de remendar: uma composição é um
        conjunto que fecha 100%, e atualizar linha a linha deixaria estados
        intermediários inválidos visíveis dentro da transação.
        """
        result = await self._session.execute(
            delete(ProductComposition).where(
                ProductComposition.tenant_id == tenant_id,
                ProductComposition.product_id == product_id,
            )
        )
        return result.rowcount or 0

    async def products_with_fiber(
        self, tenant_id: uuid.UUID, fiber_id: uuid.UUID, *, min_percent: Decimal | None = None
    ) -> list[tuple[Product, Decimal]]:
        statement = (
            select(Product, ProductComposition.percent)
            .join(ProductComposition, ProductComposition.product_id == Product.id)
            .where(
                ProductComposition.tenant_id == tenant_id,
                ProductComposition.fiber_id == fiber_id,
            )
        )
        if min_percent is not None:
            statement = statement.where(ProductComposition.percent >= min_percent)
        result = await self._session.execute(
            statement.order_by(ProductComposition.percent.desc(), Product.sku)
        )
        return list(result.tuples().all())

    async def products_without_composition(self, tenant_id: uuid.UUID) -> list[Product]:
        """Artigos ativos que ainda não têm composição cadastrada.

        Existe porque **ausência não é negativa**: eles não podem ser escondidos
        de quem perguntou por poliéster. Quem chama decide se os apresenta
        depois dos confirmados ou se avisa que o cadastro está incompleto.
        """
        com_composicao = select(ProductComposition.id).where(
            ProductComposition.product_id == Product.id,
            ProductComposition.tenant_id == tenant_id,
        )
        return list(
            await self._session.scalars(
                select(Product)
                .where(
                    Product.tenant_id == tenant_id,
                    Product.active.is_(True),
                    ~com_composicao.exists(),
                )
                .order_by(Product.sku)
            )
        )

    async def count_products_by_fiber(self, tenant_id: uuid.UUID) -> dict[uuid.UUID, int]:
        result = await self._session.execute(
            select(ProductComposition.fiber_id, func.count(ProductComposition.id))
            .where(ProductComposition.tenant_id == tenant_id)
            .group_by(ProductComposition.fiber_id)
        )
        return {fiber_id: quantos for fiber_id, quantos in result.all()}

    async def get_product_by_sku(self, tenant_id: uuid.UUID, sku: str) -> Product | None:
        """O CSV casa por SKU, que é a chave estável entre competências."""
        return await self._session.scalar(
            select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku.strip())
        )

    async def get_product(
        self, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> Product | None:
        return await self._session.scalar(
            select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id)
        )
