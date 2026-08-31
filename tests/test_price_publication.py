from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import create_schema, persist, portal_settings
from sqlalchemy import select

from crm_api.main import create_app
from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.customer import Tenant
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceEntry,
    PriceEntryRevision,
    PriceList,
    PriceListItem,
    PriceListStatus,
)
from crm_api.models.user import AuditLog
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.services.price_publication import (
    BatchNotFound,
    BatchNotPublishable,
    PricePublicationService,
)

COMPETENCIA = date.today().replace(day=1)


class Cenario:
    def __init__(self, app, tenant_id, produto_a, produto_b):
        self.app = app
        self.tenant_id = tenant_id
        self.produto_a = produto_a
        self.produto_b = produto_b

    async def publicar(self, batch_id, *, autor=None):
        async with self.app.state.session_factory() as session:
            servico = PricePublicationService(
                session=session,
                entries=PriceEntryRepository(session),
                audit=AuditRepository(session),
            )
            resultado = await servico.publish_batch(
                tenant_id=self.tenant_id, batch_id=batch_id, actor_user_id=autor
            )
            await session.commit()
            return resultado

    async def criar_lote(self, nome, itens, *, competencia=COMPETENCIA, status=None):
        lote = PriceList(
            id=uuid4(),
            tenant_id=self.tenant_id,
            name=nome,
            reference_month=competencia,
            valid_from=datetime.now(UTC) - timedelta(days=1),
            base_tax_rate=Decimal("18.000"),
            status=status or PriceListStatus.DRAFT,
        )
        async with self.app.state.session_factory() as session:
            session.add(lote)
            for produto_id, valores in itens:
                session.add(
                    PriceListItem(
                        id=uuid4(),
                        tenant_id=self.tenant_id,
                        price_list_id=lote.id,
                        product_id=produto_id,
                        **valores,
                    )
                )
            await session.commit()
        return lote.id


@pytest_asyncio.fixture
async def cenario():
    app = create_app(portal_settings())
    await create_schema(app.state.engine)

    tenant = Tenant(id=uuid4(), name="Tenant", slug="test-tenant")
    familia = ProductFamily(id=uuid4(), tenant_id=tenant.id, name="Texturizado")
    produto_a = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=familia.id,
        sku="TEX-A",
        commercial_name="75/36 cru",
    )
    produto_b = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=familia.id,
        sku="TEX-B",
        commercial_name="150/144 preto",
    )
    async with app.state.session_factory() as session:
        await persist(session, [tenant, familia, produto_a, produto_b])
        await session.commit()

    yield Cenario(app, tenant.id, produto_a.id, produto_b.id)
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_publicacao_promove_os_itens_do_lote(cenario):
    lote = await cenario.criar_lote(
        "Tabela julho",
        [
            (cenario.produto_a, {"base_price": Decimal("12.0500"),
                                 "availability": AvailabilityStatus.AVAILABLE}),
            (cenario.produto_b, {"base_price": Decimal("0"),
                                 "availability": AvailabilityStatus.OUT_OF_STOCK}),
        ],
    )

    resultado = await cenario.publicar(lote)

    assert (resultado.criados, resultado.atualizados, resultado.inalterados) == (2, 0, 0)

    async with cenario.app.state.session_factory() as session:
        entradas = list(await session.scalars(select(PriceEntry)))
        publicado = await session.scalar(select(PriceList).where(PriceList.id == lote))

    assert len(entradas) == 2
    # A alíquota do lote desce para o item quando ele não traz a sua.
    assert all(entrada.base_tax_rate == Decimal("18.000") for entrada in entradas)
    assert publicado.status is PriceListStatus.PUBLISHED


@pytest.mark.asyncio
async def test_republicar_o_mesmo_lote_e_idempotente(cenario):
    lote = await cenario.criar_lote(
        "Tabela julho",
        [(cenario.produto_a, {"base_price": Decimal("12.0500"),
                              "availability": AvailabilityStatus.AVAILABLE})],
    )

    primeira = await cenario.publicar(lote)
    segunda = await cenario.publicar(lote)

    assert primeira.criados == 1
    assert (segunda.criados, segunda.atualizados, segunda.inalterados) == (0, 0, 1)

    async with cenario.app.state.session_factory() as session:
        entradas = list(await session.scalars(select(PriceEntry)))
        revisoes = list(await session.scalars(select(PriceEntryRevision)))

    assert len(entradas) == 1
    # A segunda publicação não inventa uma revisão que não conta nada.
    assert len(revisoes) == 1


@pytest.mark.asyncio
async def test_correcao_no_meio_do_mes_vira_revisao_nao_segunda_tabela(cenario):
    """O caso da tabela especial de 20/07: mesma competência, preço corrigido."""
    normal = await cenario.criar_lote(
        "Tabela julho",
        [(cenario.produto_a, {"base_price": Decimal("12.0500"),
                              "availability": AvailabilityStatus.AVAILABLE})],
    )
    await cenario.publicar(normal)

    especial = await cenario.criar_lote(
        "Tabela ESPECIAL 20/07",
        [(cenario.produto_a, {"base_price": Decimal("11.4000"),
                              "availability": AvailabilityStatus.AVAILABLE})],
    )
    resultado = await cenario.publicar(especial)

    assert (resultado.criados, resultado.atualizados) == (0, 1)

    async with cenario.app.state.session_factory() as session:
        entradas = list(await session.scalars(select(PriceEntry)))
        revisoes = list(
            await session.scalars(
                select(PriceEntryRevision).order_by(PriceEntryRevision.changed_at)
            )
        )

    assert len(entradas) == 1
    assert entradas[0].base_price == Decimal("11.4000")
    assert entradas[0].source_batch_id == especial

    assert len(revisoes) == 2
    assert revisoes[0].previous is None
    assert revisoes[1].previous["base_price"] == "12.0500"
    assert revisoes[1].current["base_price"] == "11.4000"


@pytest.mark.asyncio
async def test_aliquota_do_item_prevalece_sobre_a_do_lote(cenario):
    lote = await cenario.criar_lote(
        "Tabela julho",
        [(cenario.produto_a, {"base_price": Decimal("10.0000"),
                              "availability": AvailabilityStatus.AVAILABLE,
                              "item_tax_rate": Decimal("12.000")})],
    )
    await cenario.publicar(lote)

    async with cenario.app.state.session_factory() as session:
        entrada = await session.scalar(select(PriceEntry))

    assert entrada.base_tax_rate == Decimal("12.000")


@pytest.mark.asyncio
async def test_competencia_futura_nao_antecipa_o_preco(cenario):
    proximo_mes = (COMPETENCIA + timedelta(days=32)).replace(day=1)
    atual = await cenario.criar_lote(
        "Tabela atual",
        [(cenario.produto_a, {"base_price": Decimal("10.0000"),
                              "availability": AvailabilityStatus.AVAILABLE})],
    )
    futuro = await cenario.criar_lote(
        "Tabela futura",
        [(cenario.produto_a, {"base_price": Decimal("99.0000"),
                              "availability": AvailabilityStatus.AVAILABLE})],
        competencia=proximo_mes,
    )
    await cenario.publicar(atual)
    await cenario.publicar(futuro)

    async with cenario.app.state.session_factory() as session:
        vigente = await PriceEntryRepository(session).latest_month(
            cenario.tenant_id, at=date.today()
        )

    assert vigente == COMPETENCIA


@pytest.mark.asyncio
async def test_a_mesma_competencia_admite_um_unico_preco_por_produto(cenario):
    lote = await cenario.criar_lote(
        "Tabela julho",
        [(cenario.produto_a, {"base_price": Decimal("10.0000"),
                              "availability": AvailabilityStatus.AVAILABLE})],
    )
    await cenario.publicar(lote)

    async with cenario.app.state.session_factory() as session:
        session.add(
            PriceEntry(
                id=uuid4(),
                tenant_id=cenario.tenant_id,
                reference_month=COMPETENCIA,
                product_id=cenario.produto_a,
                base_price=Decimal("9.0000"),
            )
        )
        with pytest.raises(Exception) as erro:
            await session.commit()
        await session.rollback()

    assert "unique" in str(erro.value).lower() or "constraint" in str(erro.value).lower()


@pytest.mark.asyncio
async def test_publicacao_e_auditada(cenario):
    lote = await cenario.criar_lote(
        "Tabela julho",
        [(cenario.produto_a, {"base_price": Decimal("10.0000"),
                              "availability": AvailabilityStatus.AVAILABLE})],
    )
    await cenario.publicar(lote)

    async with cenario.app.state.session_factory() as session:
        registro = await session.scalar(
            select(AuditLog).where(AuditLog.action == "PRICE_BATCH_PUBLISHED")
        )

    assert registro.entity_id == lote
    assert registro.after["criados"] == 1


@pytest.mark.asyncio
async def test_lote_inexistente_ou_cancelado_nao_publica(cenario):
    cancelado = await cenario.criar_lote(
        "Cancelada",
        [(cenario.produto_a, {"base_price": Decimal("10.0000"),
                              "availability": AvailabilityStatus.AVAILABLE})],
        status=PriceListStatus.CANCELLED,
    )

    with pytest.raises(BatchNotFound):
        await cenario.publicar(uuid4())

    with pytest.raises(BatchNotPublishable):
        await cenario.publicar(cancelado)

    async with cenario.app.state.session_factory() as session:
        assert list(await session.scalars(select(PriceEntry))) == []
