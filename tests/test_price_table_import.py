from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from crm_api.core.config import Settings
from crm_api.imports.price_table import activate_price_list, import_price_table
from crm_api.main import create_app
from crm_api.models.base import Base
from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.customer import Tenant
from crm_api.models.pricing import PriceList, PriceListItem, PriceListStatus


@pytest.mark.asyncio
async def test_import_creates_a_draft_price_list_and_hides_unpriced_items(tmp_path):
    app = create_app(
        Settings(
            database_url="sqlite+aiosqlite://",
            tenant_slug="test-tenant",
            internal_hmac_secret="test-secret",
        )
    )
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with app.state.session_factory() as session:
        session.add(Tenant(name="Tenant de teste", slug="test-tenant"))
        await session.commit()

    source = tmp_path / "tabela.csv"
    source.write_text(
        "family_name;family_order;sku;commercial_name;specification;availability;base_price;"
        "expected_arrival_date;arrival_note;display_order;notes\n"
        "Texturizado;10;TEX-01;Produto disponível;;AVAILABLE;12,05;;;20;Conferido\n"
        "Texturizado;10;TEX-02;Produto suspenso;;SUSPENDED;;;;10;Sem preço atual\n",
        encoding="utf-8",
    )

    async with app.state.session_factory() as session:
        async with session.begin():
            resultado = await import_price_table(
                session,
                tenant_slug="test-tenant",
                source_path=source,
                name="Tabela revisável",
                reference_month=date.today().replace(day=1),
                valid_from=datetime.now(UTC),
                valid_until=None,
            )
            price_list = resultado.price_list
            assert resultado.divergences == []

        imported = await session.scalar(select(PriceList).where(PriceList.id == price_list.id))
        items = list(
            (
                await session.execute(
                    select(PriceListItem, Product)
                    .join(Product, Product.id == PriceListItem.product_id)
                    .where(PriceListItem.price_list_id == price_list.id)
                    .order_by(PriceListItem.display_order)
                )
            ).tuples()
        )

    assert imported is not None
    assert imported.status == PriceListStatus.DRAFT
    assert [(item.display_order, product.sku, str(item.base_price)) for item, product in items] == [
        (10, "TEX-02", "0.0000"),
        (20, "TEX-01", "12.0500"),
    ]

    async with app.state.session_factory() as session:
        async with session.begin():
            activated = await activate_price_list(
                session, tenant_slug="test-tenant", price_list_id=price_list.id
            )
    assert activated.status == PriceListStatus.ACTIVE
    await app.state.engine.dispose()


async def _mundo_com_artigo(tmp_path, *, nome_no_cadastro: str, familia: str = "Texturizado"):
    """Tenant com um artigo TEX-01 já cadastrado, para provar o reencontro."""
    app = create_app(
        Settings(
            database_url="sqlite+aiosqlite://",
            tenant_slug="test-tenant",
            internal_hmac_secret="test-secret",
        )
    )
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    tenant = Tenant(id=uuid4(), name="Tenant de teste", slug="test-tenant")
    produto_familia = ProductFamily(id=uuid4(), tenant_id=tenant.id, name=familia)
    produto = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=produto_familia.id,
        sku="TEX-01",
        commercial_name=nome_no_cadastro,
    )
    async with app.state.session_factory() as session:
        session.add_all([tenant, produto_familia, produto])
        await session.commit()

    source = tmp_path / "tabela.csv"
    source.write_text(
        "family_name;family_order;sku;commercial_name;specification;availability;base_price;"
        "expected_arrival_date;arrival_note;display_order;notes\n"
        "Texturizado;10;TEX-01;Nome antigo da planilha;;AVAILABLE;12,05;;;20;\n",
        encoding="utf-8",
    )
    return app, source, produto.id


@pytest.mark.asyncio
async def test_nome_divergente_e_reportado_e_o_cadastro_prevalece(tmp_path):
    """ADR-021: quem edita pela tela não perde a edição na carga do mês."""
    app, source, produto_id = await _mundo_com_artigo(
        tmp_path, nome_no_cadastro="Nome corrigido pelo portal"
    )

    async with app.state.session_factory() as session:
        async with session.begin():
            resultado = await import_price_table(
                session,
                tenant_slug="test-tenant",
                source_path=source,
                name="Tabela do mês",
                reference_month=date.today().replace(day=1),
                valid_from=datetime.now(UTC),
                valid_until=None,
            )
        divergencias = resultado.divergences
        produto = await session.get(Product, produto_id)
        itens = list(
            await session.scalars(
                select(PriceListItem).where(
                    PriceListItem.price_list_id == resultado.price_list.id
                )
            )
        )
        nome_final = produto.commercial_name

    # A carga não parou, o preço entrou, e o nome do cadastro sobreviveu.
    assert len(itens) == 1
    assert nome_final == "Nome corrigido pelo portal"
    assert len(divergencias) == 1
    assert "TEX-01" in divergencias[0]
    assert "Nome antigo da planilha" in divergencias[0]
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_familia_divergente_continua_abortando(tmp_path):
    """Família não é redação: SKU que troca de família costuma ser SKU reusado."""
    app, source, _ = await _mundo_com_artigo(
        tmp_path, nome_no_cadastro="Nome antigo da planilha", familia="Liso"
    )

    with pytest.raises(ValueError, match="conflicts with CSV"):
        async with app.state.session_factory() as session:
            async with session.begin():
                await import_price_table(
                    session,
                    tenant_slug="test-tenant",
                    source_path=source,
                    name="Tabela do mês",
                    reference_month=date.today().replace(day=1),
                    valid_from=datetime.now(UTC),
                    valid_until=None,
                )
    await app.state.engine.dispose()
