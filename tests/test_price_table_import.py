from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from crm_api.core.config import Settings
from crm_api.imports.price_table import import_price_table
from crm_api.main import create_app
from crm_api.models.base import Base
from crm_api.models.catalog import Product
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
            price_list = await import_price_table(
                session,
                tenant_slug="test-tenant",
                source_path=source,
                name="Tabela revisável",
                reference_month=date.today().replace(day=1),
                valid_from=datetime.now(UTC),
                valid_until=None,
                activate=False,
            )

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
    await app.state.engine.dispose()
