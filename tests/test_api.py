import hashlib
import hmac
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from crm_api.core.config import Settings
from crm_api.main import create_app
from crm_api.models.base import Base
from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.customer import Customer, Tenant
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.pricing import AvailabilityStatus, PriceList, PriceListItem, PriceListStatus
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.services.price_publication import PricePublicationService


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        tenant_slug="test-tenant",
        internal_hmac_secret="test-secret",
    )


def _headers(path: str, *, tenant_slug: str = "test-tenant") -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = f"{timestamp}.GET.{path}.".encode()
    signature = hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest()
    return {
        "X-Tenant-Slug": tenant_slug,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


def _headers_with_secret(path: str, secret: bytes) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = f"{timestamp}.GET.{path}.".encode()
    signature = hmac.new(secret, canonical, hashlib.sha256).hexdigest()
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


@pytest_asyncio.fixture
async def app():
    application = create_app(_settings())
    async with application.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    tenant = Tenant(id=uuid4(), name="Tenant de teste", slug="test-tenant")
    active_customer = Customer(
        id=uuid4(),
        tenant_id=tenant.id,
        legal_name="Tecelagem Exemplo Ltda.",
        state_code="SP",
    )
    inactive_customer = Customer(
        id=uuid4(),
        tenant_id=tenant.id,
        legal_name="Cliente Inativo Ltda.",
        state_code="SP",
        active=False,
    )
    active_contact = CustomerContact(
        id=uuid4(),
        tenant_id=tenant.id,
        customer_id=active_customer.id,
        name="VitÃ³ria Exemplo",
        whatsapp_e164="+5511999999999",
    )
    inactive_contact = CustomerContact(
        id=uuid4(),
        tenant_id=tenant.id,
        customer_id=active_customer.id,
        name="Contato Inativo",
        whatsapp_e164="+5511988888888",
        active=False,
    )
    inactive_customer_contact = CustomerContact(
        id=uuid4(),
        tenant_id=tenant.id,
        customer_id=inactive_customer.id,
        name="Contato de Cliente Inativo",
        whatsapp_e164="+5511977777777",
    )
    family = ProductFamily(id=uuid4(), tenant_id=tenant.id, name="Texturizado", display_order=10)
    available_product = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=family.id,
        sku="TEX-75-36-CRU",
        commercial_name="75/36 trama cru",
    )
    unavailable_product = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=family.id,
        sku="TEX-150-144-PRETO",
        commercial_name="150/144 trama preto",
    )
    price_list = PriceList(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Tabela especial",
        reference_month=date.today().replace(day=1),
        valid_from=datetime.now(UTC) - timedelta(days=1),
        status=PriceListStatus.ACTIVE,
    )
    available_item = PriceListItem(
        id=uuid4(),
        tenant_id=tenant.id,
        price_list_id=price_list.id,
        product_id=available_product.id,
        base_price=Decimal("12.0500"),
        availability=AvailabilityStatus.AVAILABLE,
    )
    unavailable_item = PriceListItem(
        id=uuid4(),
        tenant_id=tenant.id,
        price_list_id=price_list.id,
        product_id=unavailable_product.id,
        base_price=Decimal("0"),
        availability=AvailabilityStatus.OUT_OF_STOCK,
        notes="PreÃ§o indisponÃ­vel na fonte",
    )
    async with application.state.session_factory() as session:
        session.add_all(
            [
                tenant,
                active_customer,
                inactive_customer,
                active_contact,
                inactive_contact,
                inactive_customer_contact,
                family,
                available_product,
                unavailable_product,
                price_list,
                available_item,
                unavailable_item,
            ]
        )
        await session.commit()

        # Desde a `0006` a leitura vem de `price_entries`. Publicar o lote aqui
        # faz deste arquivo o teste de contrato antes/depois: as asserções
        # abaixo são as mesmas de antes da migração e não podem mudar.
        await PricePublicationService(
            session=session,
            entries=PriceEntryRepository(session),
            audit=AuditRepository(session),
        ).publish_batch(tenant_id=tenant.id, batch_id=price_list.id)
        await session.commit()

    yield application
    await application.state.engine.dispose()


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_health_does_not_need_database(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "crm-conversacional-api"}


@pytest.mark.asyncio
async def test_ready_when_database_is_available(client):
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_hides_database_failure_details(app, client):
    class UnavailableSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def execute(self, *_):
            raise SQLAlchemyError("connection details must not be exposed")

    app.state.session_factory = UnavailableSession

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "database unavailable"


@pytest.mark.asyncio
async def test_find_customer_by_whatsapp_normalizes_presentation_characters(client):
    path = "/customers/by-whatsapp/+55%20(11)%2099999-9999"
    headers = _headers("/customers/by-whatsapp/+55 (11) 99999-9999")
    response = await client.get(path, headers=headers)

    assert response.status_code == 200
    assert response.json()["customer_name"] == "Tecelagem Exemplo Ltda."
    assert response.json()["contact_name"] == "VitÃ³ria Exemplo"
    assert response.json()["whatsapp_e164"] == "+5511999999999"


@pytest.mark.asyncio
async def test_find_customer_returns_not_found_for_absent_or_inactive_records(client):
    for phone in ("+5511966666666", "+5511988888888", "+5511977777777"):
        path = f"/customers/by-whatsapp/{phone}"
        response = await client.get(path, headers=_headers(path))
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_find_customer_rejects_invalid_phone(client):
    path = "/customers/by-whatsapp/5511999999999"
    response = await client.get(path, headers=_headers(path))

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_find_customer_rejects_invalid_tenant_signature(client):
    path = "/customers/by-whatsapp/+5511999999999"
    response = await client.get(path, headers=_headers(path, tenant_slug="other-tenant"))

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid internal request"


@pytest.mark.asyncio
async def test_find_customer_accepts_previous_hmac_key_during_rotation(app, client):
    app.state.settings.internal_hmac_previous_secret = SecretStr("previous-test-secret")
    path = "/customers/by-whatsapp/+5511999999999"
    response = await client.get(path, headers=_headers_with_secret(path, b"previous-test-secret"))

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_interaction_capabilities_are_authenticated_and_versioned(client):
    path = "/internal/interaction-capabilities"

    response = await client.get(path, headers=_headers(path))

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "crm_api"
    assert body["version"] == "1"
    assert body["session_ttl_seconds"] == 1800
    assert {intent["action"] for intent in body["intents"]} == {
        "GET_CURRENT_PRICE_LIST",
        "SEARCH_CURRENT_PRICE_LIST_ITEMS",
    }


@pytest.mark.asyncio
async def test_interaction_capabilities_reject_invalid_hmac(client):
    response = await client.get("/internal/interaction-capabilities")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_current_price_list_by_whatsapp_returns_structured_prices(client):
    path = "/price-lists/current/by-whatsapp/+5511999999999"

    response = await client.get(path, headers=_headers(path))

    assert response.status_code == 200
    body = response.json()
    assert body["customer"]["contact_id"]
    assert body["price_list"]["name"] == "Tabela especial"
    assert body["items"] == [
        {
            "product_id": body["items"][0]["product_id"],
            "family_name": "Texturizado",
            "sku": "TEX-150-144-PRETO",
            "display_name": "150/144 trama preto",
            "specification": None,
            "unit": "KG",
            "availability": "OUT_OF_STOCK",
            "base_price": None,
            "expected_arrival_date": None,
            "arrival_note": None,
            "notes": "PreÃ§o indisponÃ­vel na fonte",
        },
        {
            "product_id": body["items"][1]["product_id"],
            "family_name": "Texturizado",
            "sku": "TEX-75-36-CRU",
            "display_name": "75/36 trama cru",
            "specification": None,
            "unit": "KG",
            "availability": "AVAILABLE",
            "base_price": "12.0500",
            "expected_arrival_date": None,
            "arrival_note": None,
            "notes": None,
        },
    ]


@pytest.mark.asyncio
async def test_current_price_list_by_whatsapp_hides_inactive_contact(client):
    path = "/price-lists/current/by-whatsapp/+5511988888888"

    response = await client.get(path, headers=_headers(path))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_current_price_list_item_search_matches_active_table_terms(client):
    path = "/price-lists/current/by-whatsapp/+5511999999999/items"

    response = await client.get(f"{path}?query=75%2F36%20trama", headers=_headers(path))

    assert response.status_code == 200
    assert [item["sku"] for item in response.json()["items"]] == ["TEX-75-36-CRU"]


@pytest.mark.asyncio
async def test_current_price_list_item_search_returns_empty_items_without_a_match(client):
    path = "/price-lists/current/by-whatsapp/+5511999999999/items"

    response = await client.get(f"{path}?query=inexistente", headers=_headers(path))

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_whatsapp_number_must_be_unique_within_a_tenant(app):
    async with app.state.session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == "test-tenant"))
        customer = await session.scalar(select(Customer).where(Customer.active.is_(True)))
        session.add(
            CustomerContact(
                id=uuid4(),
                tenant_id=tenant.id,
                customer_id=customer.id,
                name="Contato Duplicado",
                whatsapp_e164="+5511999999999",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
