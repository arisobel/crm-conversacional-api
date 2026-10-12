"""Preço sem imposto no modo padrão (ADR-032).

O preço entregue é exatamente o publicado na tabela, e nenhuma configuração
fiscal ausente bloqueia a resposta. O mundo destes testes é o pior caso para a
conversão de ICMS: matriz vazia, tenant sem UF de origem e cliente sem
localidade. Ainda assim, todos os caminhos que entregam preço respondem.
"""

import hashlib
import hmac
import re
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from conftest import PASSWORD, REPRESENTATIVE_A_EMAIL, build_portal_world, login
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from crm_api.models.customer import CustomerLocation, Tenant
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.pricing import AvailabilityStatus, PriceEntry
from crm_api.models.tax import IcmsRule
from crm_api.models.user import User
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository, PortfolioScope
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.services.customer_price_list import CustomerPriceListService

PRECO_PUBLICADO = "12.0500"
COMPETENCIA = date.today().replace(day=1)
TELEFONE_REPRESENTANTE = "+5511987654321"
TELEFONE_CLIENTE = "+5511988887777"
_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


async def _montar(
    *, availability: AvailabilityStatus = AvailabilityStatus.AVAILABLE, **setting_overrides
):
    """Preço publicado e nada fiscal: sem regra, sem origem, sem localidade."""
    mundo = await build_portal_world(**setting_overrides)
    async with mundo.app.state.session_factory() as session:
        tenant = await session.get(Tenant, mundo.tenant_id)
        assert tenant.origin_state_code is None

        representante = await session.get(User, mundo.representative_a_id)
        representante.whatsapp_e164 = TELEFONE_REPRESENTANTE

        session.add(
            CustomerContact(
                id=uuid4(),
                tenant_id=mundo.tenant_id,
                customer_id=mundo.customer_a_id,
                name="Compras Alfa",
                whatsapp_e164=TELEFONE_CLIENTE,
                is_primary=True,
            )
        )
        session.add(
            PriceEntry(
                id=uuid4(),
                tenant_id=mundo.tenant_id,
                reference_month=COMPETENCIA,
                product_id=mundo.product_id,
                base_price=Decimal(PRECO_PUBLICADO),
                base_tax_rate=Decimal("18.000"),
                availability=availability,
                published_at=datetime.now(UTC),
            )
        )
        await session.execute(
            delete(CustomerLocation).where(CustomerLocation.customer_id == mundo.customer_a_id)
        )
        await session.commit()

        assert await session.scalar(select(func.count()).select_from(IcmsRule)) == 0
    return mundo


@asynccontextmanager
async def _mundo(**kwargs):
    mundo = await _montar(**kwargs)
    try:
        yield mundo
    finally:
        await mundo.app.state.engine.dispose()


def _headers(path: str) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join([timestamp.encode(), b"GET", path.encode(), b""])
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest(),
    }


async def _get_interno(mundo, path: str, *, params: dict | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=mundo.app), base_url="http://testserver"
    ) as client:
        return await client.get(path, params=params, headers=_headers(path))


class _ResolverProibido:
    async def resolve(self, **_):
        raise AssertionError("o resolver de ICMS não pode ser consultado no modo NONE")


# --------------------------------------------------------------- serviço


@pytest.mark.asyncio
async def test_padrao_entrega_o_preco_publicado_sem_consultar_o_icms():
    async with _mundo() as mundo:
        assert mundo.app.state.settings.icms_conversion_mode == "NONE"

        async with mundo.app.state.session_factory() as session:
            resolvida = await CustomerPriceListService(
                portfolio=CustomerPortfolioRepository(session),
                admin=CustomerAdminRepository(session),
                entries=PriceEntryRepository(session),
                resolver=_ResolverProibido(),
                settings=mundo.app.state.settings,
            ).resolve(
                PortfolioScope(tenant_id=mundo.tenant_id, owner_user_id=None),
                mundo.customer_a_id,
                origin_state=None,
            )

    assert resolvida.converted is False
    assert resolvida.location is None
    assert resolvida.origin_state is None
    assert resolvida.destination_state is None
    [item] = resolvida.items
    assert item.final_price == item.base_price == Decimal(PRECO_PUBLICADO)
    assert item.tax_rate is None
    assert item.trace is None


@pytest.mark.asyncio
async def test_item_sem_preco_comercial_continua_sem_preco():
    async with _mundo(availability=AvailabilityStatus.CONSULT) as mundo:
        resposta = await _get_interno(
            mundo,
            f"/internal/representative/by-whatsapp/{TELEFONE_REPRESENTANTE}"
            f"/customers/{mundo.customer_a_id}/price-list",
        )

    assert resposta.status_code == 200
    [item] = resposta.json()["items"]
    assert item["base_price"] is None
    assert item["final_price"] is None


# ------------------------------------------------- WhatsApp do representante


@pytest.mark.asyncio
async def test_representante_recebe_tabela_de_cliente_sem_localidade():
    async with _mundo() as mundo:
        resposta = await _get_interno(
            mundo,
            f"/internal/representative/by-whatsapp/{TELEFONE_REPRESENTANTE}"
            f"/customers/{mundo.customer_a_id}/price-list",
        )

    assert resposta.status_code == 200
    corpo = resposta.json()
    # UF preenchida faria o Gateway escrever "já com ICMS para <UF>".
    assert corpo["origin_state"] is None
    assert corpo["destination_state"] is None
    [item] = corpo["items"]
    assert item["final_price"] == item["base_price"] == PRECO_PUBLICADO
    assert item["tax_rate"] is None


@pytest.mark.asyncio
async def test_busca_de_artigo_do_representante_traz_o_preco_publicado():
    async with _mundo() as mundo:
        resposta = await _get_interno(
            mundo,
            f"/internal/representative/by-whatsapp/{TELEFONE_REPRESENTANTE}/price-items",
            params={"query": "75/36"},
        )

    assert resposta.status_code == 200
    [item] = resposta.json()["items"]
    assert item["base_price"] == PRECO_PUBLICADO


# ---------------------------------------------------------- WhatsApp do cliente


@pytest.mark.asyncio
@pytest.mark.parametrize("preferidos", [False, True], ids=["catalogo", "preferidos"])
async def test_cliente_sem_localidade_recebe_o_preco_publicado(preferidos):
    async with _mundo(whatsapp_icms_enabled=preferidos) as mundo:
        resposta = await _get_interno(
            mundo, f"/price-lists/current/by-whatsapp/{TELEFONE_CLIENTE}"
        )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["origin_state"] is None
    assert corpo["destination_state"] is None
    [item] = corpo["items"]
    assert item["base_price"] == PRECO_PUBLICADO
    assert item["final_price"] in (None, PRECO_PUBLICADO)
    assert item["tax_rate"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("preferidos", [False, True], ids=["catalogo", "preferidos"])
async def test_busca_de_artigo_do_cliente_traz_o_preco_publicado(preferidos):
    async with _mundo(whatsapp_icms_enabled=preferidos) as mundo:
        resposta = await _get_interno(
            mundo,
            f"/price-lists/current/by-whatsapp/{TELEFONE_CLIENTE}/items",
            params={"query": "75/36"},
        )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["destination_state"] is None
    [item] = corpo["items"]
    assert item["base_price"] == PRECO_PUBLICADO
    assert item["final_price"] in (None, PRECO_PUBLICADO)


# ------------------------------------------------------------- portal e API


@pytest.mark.asyncio
async def test_api_admin_entrega_a_lista_sem_localidade_nem_matriz():
    async with _mundo() as mundo:
        async with AsyncClient(
            transport=ASGITransport(app=mundo.app), base_url="http://test"
        ) as client:
            await login(client, email=REPRESENTATIVE_A_EMAIL)
            resposta = await client.get(f"/admin/customers/{mundo.customer_a_id}/price-list")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["location_id"] is None
    assert corpo["origin_state"] is None
    assert corpo["destination_state"] is None
    [item] = corpo["items"]
    assert item["final_price"] == item["base_price"] == PRECO_PUBLICADO
    assert item["tax_rate"] is None


@pytest.mark.asyncio
async def test_portal_mostra_o_preco_publicado_sem_falar_de_imposto():
    async with _mundo() as mundo:
        async with AsyncClient(
            transport=ASGITransport(app=mundo.app),
            base_url="http://test",
            follow_redirects=True,
        ) as client:
            pagina = await client.get("/portal/login")
            await client.post(
                "/portal/login",
                data={
                    "email": REPRESENTATIVE_A_EMAIL,
                    "password": PASSWORD,
                    "csrf_token": _CSRF.search(pagina.text).group(1),
                },
            )
            tela = await client.get(f"/portal/customers/{mundo.customer_a_id}/price-list")
            csv = await client.get(
                f"/portal/customers/{mundo.customer_a_id}/price-list?formato=csv"
            )

    assert tela.status_code == 200
    assert PRECO_PUBLICADO in tela.text
    assert "sem conversão de imposto" in tela.text
    assert "Não há regra de ICMS" not in tela.text
    assert "Alíquota" not in tela.text

    assert csv.status_code == 200
    # Vírgula decimal, para o Excel em português; o final é o publicado.
    assert ";12,0500;;12,0500;" in csv.text
