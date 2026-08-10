"""Cadastro de artigo pelo portal.

O artigo nasce em duas peças: o produto no catálogo, que passa a existir na
hora, e o preço, que entra como **item de um lote em rascunho** da competência
corrente. O preço só vale depois que alguém publicar o lote em `/portal/prices`.

Essa separação é o ADR-009 aplicado à tela: gravar direto em `price_entries`
faria a rota que o Gateway consome servir, no mesmo segundo, um preço que
ninguém revisou — e sem `source_batch_id` a trilha de revisões perderia a
origem. O caminho mais longo é o que mantém publicação e revisão existindo.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.pricing import (
    NO_PRICE_AVAILABILITIES,
    AvailabilityStatus,
    PriceList,
    PriceListItem,
    PriceListStatus,
)
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.catalog import CatalogRepository

# Nome do lote que recebe as inclusões feitas pela tela. Fixo de propósito: com
# a competência ele forma a chave `(tenant, nome, competência)`, e um nome fixo
# faz o segundo artigo do mês cair no mesmo lote em vez de criar um lote por
# artigo — publicar cinquenta lotes de uma linha não é revisão, é ruído.
BATCH_NAME = "Inclusões pelo portal"


class IncompleteArticle(Exception):
    """SKU ou nome comercial ausente."""


class DuplicateSku(Exception):
    """Já existe um produto com este SKU no tenant."""


class FamilyRequired(Exception):
    """Nem família existente, nem nome de família nova."""


class FamilyNotFound(Exception):
    """Família inexistente neste tenant."""


class DuplicateFamily(Exception):
    """Já existe uma família com este nome no tenant."""


class ArticleNotFound(Exception):
    """Artigo inexistente neste tenant.

    Nome próprio para não colidir com `ProductNotFound` de `customer_admin`,
    que responde por outra pergunta: o produto que o cliente quer preferir.
    """


class SkuLocked(Exception):
    """O artigo já tem preço publicado; o SKU deixou de ser editável."""


class BasePriceRequired(Exception):
    """Disponibilidade que exige preço veio sem preço."""


class InvalidBasePrice(Exception):
    """Preço negativo."""


class ArticleCreated:
    """Resultado da criação, com o que a tela precisa dizer ao usuário."""

    __slots__ = ("product", "family", "batch", "item", "family_created")

    def __init__(
        self,
        *,
        product: Product,
        family: ProductFamily,
        batch: PriceList,
        item: PriceListItem,
        family_created: bool,
    ) -> None:
        self.product = product
        self.family = family
        self.batch = batch
        self.item = item
        self.family_created = family_created


class CatalogService:
    def __init__(self, *, catalog: CatalogRepository, audit: AuditRepository) -> None:
        self._catalog = catalog
        self._audit = audit

    # ------------------------------------------------------- criar e alterar

    async def create_product(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        sku: str,
        commercial_name: str,
        family_id: uuid.UUID | None = None,
        family_name: str | None = None,
        specification: str | None = None,
        unit: str = "KG",
        request_id: str | None = None,
    ) -> tuple[Product, ProductFamily, bool]:
        """Cria só o artigo no catálogo, sem preço nenhum.

        Existe separado de `create_article` porque a tela de produtos cadastra
        artigo que ainda não vai à tabela — o preço chega na importação do mês.
        """
        sku = sku.strip()
        commercial_name = commercial_name.strip()
        if not sku or not commercial_name:
            raise IncompleteArticle
        if await self._catalog.sku_exists(tenant_id, sku):
            raise DuplicateSku

        family, family_created = await self._family(tenant_id, family_id, family_name)
        product = Product(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            family_id=family.id,
            sku=sku,
            commercial_name=commercial_name,
            specification=(specification or "").strip() or None,
            unit=(unit or "KG").strip().upper(),
        )
        self._catalog.add(product)
        self._audit.record(
            action="PRODUCT_CREATED",
            entity="products",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=product.id,
            after={
                "sku": product.sku,
                "commercial_name": product.commercial_name,
                "family": family.name,
                "family_created": family_created,
                "source": "portal",
            },
            request_id=request_id,
        )
        await self._catalog.flush()
        return product, family, family_created

    async def add_draft_price(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product: Product,
        base_price: Decimal | None,
        availability: AvailabilityStatus,
        reference_month: date | None = None,
        request_id: str | None = None,
    ) -> tuple[PriceList, PriceListItem]:
        self._validar_preco(base_price, availability)
        competencia = (reference_month or datetime.now(UTC).date()).replace(day=1)
        batch = await self._draft_batch(tenant_id, competencia)
        item = PriceListItem(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            price_list_id=batch.id,
            product_id=product.id,
            # Sem preço a coluna não aceita nulo; o zero só existe nas
            # disponibilidades que não cotam, e `availability` é o que a tela
            # mostra. É a mesma convenção da importação por CSV.
            base_price=base_price if base_price is not None else Decimal("0"),
            availability=availability,
            display_order=await self._catalog.count_batch_items(batch.id),
        )
        self._catalog.add(item)
        self._audit.record(
            action="PRICE_DRAFT_ITEM_CREATED",
            entity="price_list_items",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=item.id,
            after={
                "batch_id": str(batch.id),
                "reference_month": competencia.isoformat(),
                "product_id": str(product.id),
                "base_price": str(item.base_price),
                "availability": item.availability.value,
                "source": "portal",
            },
            request_id=request_id,
        )
        await self._catalog.flush()
        return batch, item

    async def create_article(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        sku: str,
        commercial_name: str,
        family_id: uuid.UUID | None = None,
        family_name: str | None = None,
        specification: str | None = None,
        unit: str = "KG",
        base_price: Decimal | None = None,
        availability: AvailabilityStatus = AvailabilityStatus.AVAILABLE,
        reference_month: date | None = None,
        request_id: str | None = None,
    ) -> ArticleCreated:
        """Artigo e preço de rascunho na mesma transação — o caminho da ficha."""
        # O preço é validado antes de o produto existir: recusar depois deixaria
        # um artigo órfão no catálogo se a transação não fosse desfeita.
        self._validar_preco(base_price, availability)

        product, family, family_created = await self.create_product(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            sku=sku,
            commercial_name=commercial_name,
            family_id=family_id,
            family_name=family_name,
            specification=specification,
            unit=unit,
            request_id=request_id,
        )
        batch, item = await self.add_draft_price(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            product=product,
            base_price=base_price,
            availability=availability,
            reference_month=reference_month,
            request_id=request_id,
        )
        return ArticleCreated(
            product=product,
            family=family,
            batch=batch,
            item=item,
            family_created=family_created,
        )

    async def update_product(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        commercial_name: str,
        family_id: uuid.UUID | None = None,
        family_name: str | None = None,
        sku: str | None = None,
        specification: str | None = None,
        unit: str | None = None,
        request_id: str | None = None,
    ) -> Product:
        product = await self._catalog.get_product(tenant_id, product_id)
        if product is None:
            raise ArticleNotFound

        commercial_name = commercial_name.strip()
        if not commercial_name:
            raise IncompleteArticle

        antes = {
            "sku": product.sku,
            "commercial_name": product.commercial_name,
            "specification": product.specification,
            "unit": product.unit,
            "family_id": str(product.family_id),
        }

        novo_sku = (sku or "").strip()
        if novo_sku and novo_sku != product.sku:
            # A trava é o preço publicado, não a existência do artigo: enquanto
            # nenhuma competência o carregou, o SKU ainda é rascunho de quem
            # digitou.
            if await self._catalog.has_published_price(tenant_id, product_id):
                raise SkuLocked
            if await self._catalog.sku_exists(tenant_id, novo_sku, excluding=product_id):
                raise DuplicateSku
            product.sku = novo_sku

        family, _ = await self._family(tenant_id, family_id, family_name)
        product.family_id = family.id
        product.commercial_name = commercial_name
        product.specification = (specification or "").strip() or None
        product.unit = (unit or product.unit).strip().upper()

        self._audit.record(
            action="PRODUCT_UPDATED",
            entity="products",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=product.id,
            before=antes,
            after={
                "sku": product.sku,
                "commercial_name": product.commercial_name,
                "specification": product.specification,
                "unit": product.unit,
                "family_id": str(product.family_id),
            },
            request_id=request_id,
        )
        await self._catalog.flush()
        return product

    async def set_product_active(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        active: bool,
        request_id: str | None = None,
    ) -> Product:
        """Ativa ou desativa o artigo.

        Desativar não apaga nem desfaz preferência de cliente: o artigo apenas
        deixa de sair na tabela do mês e na lista do representante, que é o que
        `Product.active` filtra. A preferência continua registrada, e reativar o
        artigo a traz de volta inteira.
        """
        product = await self._catalog.get_product(tenant_id, product_id)
        if product is None:
            raise ArticleNotFound

        antes = product.active
        product.active = active
        self._audit.record(
            action="PRODUCT_ACTIVATED" if active else "PRODUCT_DEACTIVATED",
            entity="products",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=product.id,
            before={"active": antes},
            after={"active": active, "sku": product.sku},
            request_id=request_id,
        )
        await self._catalog.flush()
        return product

    # ------------------------------------------------------------- famílias

    async def create_family(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        name: str,
        display_order: int | None = None,
        request_id: str | None = None,
    ) -> ProductFamily:
        nome = name.strip()
        if not nome:
            raise FamilyRequired
        if await self._catalog.family_name_taken(tenant_id, nome):
            raise DuplicateFamily

        family = ProductFamily(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=nome,
            display_order=(
                display_order
                if display_order is not None
                else await self._catalog.next_family_order(tenant_id)
            ),
        )
        self._catalog.add(family)
        self._audit.record(
            action="PRODUCT_FAMILY_CREATED",
            entity="product_families",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=family.id,
            after={"name": family.name, "display_order": family.display_order},
            request_id=request_id,
        )
        await self._catalog.flush()
        return family

    async def update_family(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        family_id: uuid.UUID,
        name: str | None = None,
        display_order: int | None = None,
        active: bool | None = None,
        request_id: str | None = None,
    ) -> ProductFamily:
        family = await self._catalog.get_family(tenant_id, family_id)
        if family is None:
            raise FamilyNotFound

        antes = {
            "name": family.name,
            "display_order": family.display_order,
            "active": family.active,
        }

        if name is not None:
            nome = name.strip()
            if not nome:
                raise FamilyRequired
            if await self._catalog.family_name_taken(tenant_id, nome, excluding=family_id):
                raise DuplicateFamily
            family.name = nome
        if display_order is not None:
            family.display_order = display_order
        if active is not None:
            family.active = active

        self._audit.record(
            action="PRODUCT_FAMILY_UPDATED",
            entity="product_families",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=family.id,
            before=antes,
            after={
                "name": family.name,
                "display_order": family.display_order,
                "active": family.active,
            },
            request_id=request_id,
        )
        await self._catalog.flush()
        return family

    # ---------------------------------------------------------------- apoio

    def _validar_preco(
        self, base_price: Decimal | None, availability: AvailabilityStatus
    ) -> None:
        if base_price is None and availability not in NO_PRICE_AVAILABILITIES:
            raise BasePriceRequired
        if base_price is not None and base_price < 0:
            raise InvalidBasePrice

    async def _family(
        self, tenant_id: uuid.UUID, family_id: uuid.UUID | None, family_name: str | None
    ) -> tuple[ProductFamily, bool]:
        if family_id is not None:
            family = await self._catalog.get_family(tenant_id, family_id)
            if family is None:
                raise FamilyNotFound
            return family, False

        nome = (family_name or "").strip()
        if not nome:
            raise FamilyRequired

        # Digitar o nome de uma família que já existe reaproveita a existente em
        # vez de bater na unicidade `(tenant, name)` com um erro de banco.
        existente = await self._catalog.find_family_by_name(tenant_id, nome)
        if existente is not None:
            return existente, False

        family = ProductFamily(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=nome,
            display_order=await self._catalog.next_family_order(tenant_id),
        )
        self._catalog.add(family)
        await self._catalog.flush()
        return family, True

    async def _draft_batch(self, tenant_id: uuid.UUID, competencia: date) -> PriceList:
        existente = await self._catalog.find_draft_batch(tenant_id, competencia, BATCH_NAME)
        if existente is not None:
            return existente

        # O lote do mês pode já ter sido publicado — e um lote publicado não
        # recebe item novo, senão ele passaria a mentir sobre o próprio estado.
        # Nesse caso abre-se o lote seguinte, com nome livre, porque a chave
        # `(tenant, nome, competência)` não admite repetição.
        nome = await self._catalog.free_batch_name(tenant_id, competencia, BATCH_NAME)
        batch = PriceList(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=nome,
            reference_month=competencia,
            valid_from=datetime.now(UTC),
            status=PriceListStatus.DRAFT,
        )
        self._catalog.add(batch)
        await self._catalog.flush()
        return batch
