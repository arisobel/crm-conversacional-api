"""Tabela do WhatsApp com o interruptor de ICMS ligado.

O regime desligado é coberto por `tests/test_api.py`, que é o teste de contrato
com o Gateway em produção. Aqui exercita-se o outro regime: produtos preferidos
do cliente, preço convertido para a UF onde ele recebe e erros distinguíveis.
"""

import hashlib
import hmac
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import TEST_DATABASE_URL, create_schema, persist
from httpx import ASGITransport, AsyncClient

from crm_api.core.config import Settings
from crm_api.main import create_app
from crm_api.models.catalog import (
    CustomerPreferredProduct,
    Product,
    ProductFamily,
)
from crm_api.models.customer import Customer, CustomerLocation, Tenant
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.pricing import AvailabilityStatus, PriceEntry
from crm_api.models.tax import IcmsRule

TELEFONE = "+5511999999999"
COMPETENCIA = date.today().replace(day=1)
CAMINHO = f"/price-lists/current/by-whatsapp/{TELEFONE}"


def _settings(**overrides) -> Settings:
    valores = {
        "database_url": TEST_DATABASE_URL,
        "tenant_slug": "test-tenant",
        "internal_hmac_secret": "test-secret",
        "whatsapp_icms_enabled": True,
    }
    valores.update(overrides)
    return Settings(**valores)


def _headers(path: str) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = f"{timestamp}.GET.{path}.".encode()
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest(),
    }


async def _montar(
    *,
    com_regra: bool = True,
    com_preferido: bool = True,
    origem: str | None = "SP",
    destino: str = "RS",
    com_localidade: bool = True,
    com_competencia: bool = True,
    **setting_overrides,
):
    application = create_app(_settings(**setting_overrides))
    await create_schema(application.state.engine)

    tenant = Tenant(
        id=uuid4(), name="Tenant de teste", slug="test-tenant", origin_state_code=origem
    )
    cliente = Customer(
        id=uuid4(), tenant_id=tenant.id, legal_name="Tecelagem Exemplo Ltda.", state_code="SP"
    )
    contato = CustomerContact(
        id=uuid4(),
        tenant_id=tenant.id,
        customer_id=cliente.id,
        name="Vitória Exemplo",
        whatsapp_e164=TELEFONE,
    )
    familia = ProductFamily(id=uuid4(), tenant_id=tenant.id, name="Texturizado")
    preferido = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=familia.id,
        sku="TEX-75-36-CRU",
        commercial_name="75/36 trama cru",
    )
    outro = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=familia.id,
        sku="TEX-150-144-PRETO",
        commercial_name="150/144 trama preto",
    )

    registros = [tenant, cliente, contato, familia, preferido, outro]

    if com_localidade:
        registros.append(
            CustomerLocation(
                id=uuid4(),
                tenant_id=tenant.id,
                customer_id=cliente.id,
                label="Principal",
                state_code=destino,
                is_default=True,
            )
        )
    if com_preferido:
        registros.append(
            CustomerPreferredProduct(
                id=uuid4(),
                tenant_id=tenant.id,
                customer_id=cliente.id,
                product_id=preferido.id,
                customer_alias="o cru de sempre",
            )
        )
    if com_competencia:
        registros += [
            PriceEntry(
                id=uuid4(),
                tenant_id=tenant.id,
                reference_month=COMPETENCIA,
                product_id=produto.id,
                base_price=Decimal("12.0500"),
                base_tax_rate=Decimal("18.000"),
                availability=AvailabilityStatus.AVAILABLE,
                published_at=datetime.now(UTC),
            )
            for produto in (preferido, outro)
        ]
    if com_regra:
        registros.append(
            IcmsRule(
                id=uuid4(),
                tenant_id=tenant.id,
                origin_state=origem or "SP",
                destination_state=destino,
                tax_rate=Decimal("12.000"),
                valid_from=date.today() - timedelta(days=1),
            )
        )

    async with application.state.session_factory() as session:
        await persist(session, registros)
        await session.commit()

    return application, preferido.id, outro.id


@pytest_asyncio.fixture
async def mundo():
    application, preferido_id, outro_id = await _montar()
    yield application, preferido_id, outro_id
    await application.state.engine.dispose()


async def _buscar(application, caminho: str = CAMINHO):
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(caminho, headers=_headers(caminho))


@pytest.mark.asyncio
async def test_tabela_sai_convertida_para_a_uf_do_cliente(mundo):
    application, preferido_id, _ = mundo

    resposta = await _buscar(application)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["origin_state"] == "SP"
    assert corpo["destination_state"] == "RS"

    item = corpo["items"][0]
    # 12,05 com 18% embutido, vendido para UF de 12%: 12,05 x 0,82 / 0,88.
    assert item["final_price"] == "11.2284"
    assert item["tax_rate"] == "12.000"
    # `base_price` continua na resposta: é o que um Gateway anterior lê.
    assert item["base_price"] == "12.0500"


@pytest.mark.asyncio
async def test_tabela_traz_so_os_preferidos_com_o_apelido_do_cliente(mundo):
    application, preferido_id, outro_id = mundo

    corpo = (await _buscar(application)).json()

    assert [item["product_id"] for item in corpo["items"]] == [str(preferido_id)]
    assert corpo["items"][0]["display_name"] == "o cru de sempre"


@pytest.mark.asyncio
async def test_cliente_sem_preferidos_recebe_o_catalogo():
    application, _, _ = await _montar(com_preferido=False)
    try:
        corpo = (await _buscar(application)).json()
    finally:
        await application.state.engine.dispose()

    assert len(corpo["items"]) == 2


@pytest.mark.asyncio
async def test_regra_de_icms_ausente_responde_conflito():
    application, _, _ = await _montar(com_regra=False)
    try:
        resposta = await _buscar(application)
    finally:
        await application.state.engine.dispose()

    # 409, e não 404: a tabela existe; falta a regra que permite exibi-la aqui.
    # Nenhum preço estimado sai — é a trava que protege o cliente.
    assert resposta.status_code == 409


@pytest.mark.asyncio
async def test_uf_de_origem_ausente_responde_422():
    application, _, _ = await _montar(origem=None)
    try:
        resposta = await _buscar(application)
    finally:
        await application.state.engine.dispose()

    assert resposta.status_code == 422


@pytest.mark.asyncio
async def test_cliente_sem_localidade_responde_422():
    application, _, _ = await _montar(com_localidade=False)
    try:
        resposta = await _buscar(application)
    finally:
        await application.state.engine.dispose()

    assert resposta.status_code == 422


@pytest.mark.asyncio
async def test_sem_competencia_publicada_responde_422():
    application, _, _ = await _montar(com_competencia=False)
    try:
        resposta = await _buscar(application)
    finally:
        await application.state.engine.dispose()

    assert resposta.status_code == 422


@pytest.mark.asyncio
async def test_contato_desconhecido_continua_404(mundo):
    application, _, _ = mundo
    caminho = "/price-lists/current/by-whatsapp/+5541900000000"

    resposta = await _buscar(application, caminho)

    # Contato desconhecido é o único caso que permanece 404 nos dois regimes.
    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_busca_por_item_tambem_sai_convertida(mundo):
    application, _, _ = mundo
    caminho = f"{CAMINHO}/items"

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resposta = await client.get(f"{caminho}?query=75%2F36", headers=_headers(caminho))

    assert resposta.status_code == 200
    assert resposta.json()["items"][0]["final_price"] == "11.2284"


@pytest.mark.asyncio
async def test_desligado_devolve_base_sem_praca():
    """A mesma base, com o interruptor desligado, volta ao regime antigo."""
    application, _, _ = await _montar(whatsapp_icms_enabled=False)
    try:
        corpo = (await _buscar(application)).json()
    finally:
        await application.state.engine.dispose()

    assert corpo["origin_state"] is None
    assert corpo["destination_state"] is None
    assert all(item["final_price"] is None for item in corpo["items"])
    # Catálogo inteiro, não o recorte por preferidos.
    assert len(corpo["items"]) == 2
