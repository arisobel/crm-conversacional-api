"""Leituras que resolvem o público de uma campanha (F6.2).

Separado do `WhatsappCampaignRepository` de propósito: aquele guarda campanhas,
este atravessa carteira, catálogo, grupos e composição para descobrir quem
entra. São perguntas diferentes sobre tabelas diferentes.

Como no `CustomerPortfolioRepository`, **o escopo é argumento obrigatório de
toda consulta que devolve cliente**. Não existe leitura de audiência sem
tenant, e a carteira entra na mesma cláusula — filtrar depois, em memória,
deixaria a porta aberta para uma chamada nova esquecer.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import (
    CustomerPreferredProduct,
    Product,
    ProductGroup,
    ProductGroupMember,
)
from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.textile import Fiber, ProductComposition


class AudienceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    # ------------------------------------------------ existência de critério

    async def existing_group_ids(
        self, tenant_id: uuid.UUID, group_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Quais dos grupos pedidos existem e estão ativos neste tenant.

        Serve para o resolvedor **falhar** diante de um grupo inexistente, em
        vez de devolver um público menor sem explicar por quê — que é a forma
        silenciosa de errar o alvo.
        """
        if not group_ids:
            return set()
        return set(
            await self._session.scalars(
                select(ProductGroup.id).where(
                    ProductGroup.tenant_id == tenant_id,
                    ProductGroup.id.in_(group_ids),
                    ProductGroup.active.is_(True),
                )
            )
        )

    async def existing_product_ids(
        self, tenant_id: uuid.UUID, product_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        if not product_ids:
            return set()
        return set(
            await self._session.scalars(
                select(Product.id).where(
                    Product.tenant_id == tenant_id,
                    Product.id.in_(product_ids),
                    Product.active.is_(True),
                )
            )
        )

    async def fibers_by_codes(
        self, tenant_id: uuid.UUID, codes: list[str]
    ) -> dict[str, Fiber]:
        """Resolve siglas do setor (`PES`, `CO`) para as fibras do tenant."""
        canonicos = {code.strip().upper() for code in codes if code.strip()}
        if not canonicos:
            return {}
        encontradas = await self._session.scalars(
            select(Fiber).where(
                Fiber.tenant_id == tenant_id,
                Fiber.code.in_(canonicos),
                Fiber.active.is_(True),
            )
        )
        return {fibra.code: fibra for fibra in encontradas}

    # ------------------------------------------------------ eixos de produto

    async def products_in_groups(
        self, tenant_id: uuid.UUID, group_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Artigos ativos que pertencem a **algum** dos grupos pedidos."""
        if not group_ids:
            return set()
        return set(
            await self._session.scalars(
                select(ProductGroupMember.product_id)
                .join(Product, Product.id == ProductGroupMember.product_id)
                .where(
                    ProductGroupMember.tenant_id == tenant_id,
                    ProductGroupMember.group_id.in_(group_ids),
                    Product.active.is_(True),
                )
            )
        )

    async def products_with_fibers(
        self,
        tenant_id: uuid.UUID,
        fiber_ids: list[uuid.UUID],
        *,
        min_percent: Decimal | None = None,
    ) -> set[uuid.UUID]:
        """Artigos ativos com composição declarada de alguma das fibras."""
        if not fiber_ids:
            return set()
        statement = (
            select(ProductComposition.product_id)
            .join(Product, Product.id == ProductComposition.product_id)
            .where(
                ProductComposition.tenant_id == tenant_id,
                ProductComposition.fiber_id.in_(fiber_ids),
                Product.active.is_(True),
            )
        )
        if min_percent is not None:
            statement = statement.where(ProductComposition.percent >= min_percent)
        return set(await self._session.scalars(statement))

    async def products_without_composition(self, tenant_id: uuid.UUID) -> set[uuid.UUID]:
        """Artigos ativos sem nenhuma linha de composição.

        **Ausência não é negativa** (ADR-027): estes artigos não são "sem
        poliéster", são artigos cujo cadastro não foi feito. Quem consulta
        precisa deles para poder *avisar* em vez de encolher o público em
        silêncio.
        """
        com_composicao = select(ProductComposition.id).where(
            ProductComposition.product_id == Product.id,
            ProductComposition.tenant_id == tenant_id,
        )
        return set(
            await self._session.scalars(
                select(Product.id).where(
                    Product.tenant_id == tenant_id,
                    Product.active.is_(True),
                    ~com_composicao.exists(),
                )
            )
        )

    # ---------------------------------------------------------- audiência

    async def customers_in_scope(
        self,
        tenant_id: uuid.UUID,
        *,
        owner_user_id: uuid.UUID,
        state_codes: list[str] | None = None,
        preferring_any_of: set[uuid.UUID] | None = None,
    ) -> list[Customer]:
        """Clientes ativos da carteira, opcionalmente recortados.

        `owner_user_id` **não** é opcional: esta consulta nunca devolve carteira
        alheia, qualquer que seja o papel de quem pergunta. A alçada de
        `ADMIN`/`MANAGER` sobre outra carteira é pendência da F6.0, e enquanto
        ela não existir não há caminho de código que a exerça.

        `preferring_any_of` vazio (conjunto sem elementos) devolve lista vazia,
        e isso é diferente de `None`: nenhum artigo casou com o critério, então
        nenhum cliente casa. Só `None` significa "sem recorte de produto".
        """
        statement = select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.owner_user_id == owner_user_id,
            Customer.active.is_(True),
        )
        if state_codes:
            statement = statement.where(Customer.state_code.in_(state_codes))
        if preferring_any_of is not None:
            if not preferring_any_of:
                return []
            prefere = select(CustomerPreferredProduct.id).where(
                CustomerPreferredProduct.customer_id == Customer.id,
                CustomerPreferredProduct.tenant_id == tenant_id,
                CustomerPreferredProduct.product_id.in_(preferring_any_of),
                CustomerPreferredProduct.active.is_(True),
            )
            statement = statement.where(prefere.exists())
        # Ordem estável: a mesma prévia, na mesma ordem, para os mesmos dados.
        # Sem isto, duas execuções idênticas produziriam listas diferentes e
        # "reproduzível" viraria força de expressão.
        return list(
            await self._session.scalars(statement.order_by(Customer.legal_name, Customer.id))
        )

    async def active_contacts(
        self, tenant_id: uuid.UUID, customer_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[CustomerContact]]:
        """Contatos ativos por cliente, numa consulta só.

        O principal vem primeiro, e o resto por data de criação — a política de
        escolha do destinatário depende dessa ordem ser determinística.
        """
        if not customer_ids:
            return {}
        linhas = await self._session.scalars(
            select(CustomerContact)
            .where(
                CustomerContact.tenant_id == tenant_id,
                CustomerContact.customer_id.in_(customer_ids),
                CustomerContact.active.is_(True),
            )
            .order_by(
                CustomerContact.customer_id,
                CustomerContact.is_primary.desc(),
                CustomerContact.created_at,
                CustomerContact.id,
            )
        )
        por_cliente: dict[uuid.UUID, list[CustomerContact]] = {}
        for contato in linhas:
            por_cliente.setdefault(contato.customer_id, []).append(contato)
        return por_cliente
