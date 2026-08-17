"""As três leituras do representante pelo WhatsApp (W6).

O que está sob teste, além do caminho felizardo, é o escopo: um representante
não alcança cliente de outra carteira, e um `ADMIN` — que no portal vê o tenant
inteiro — **também não**, porque o canal autentica por número de telefone.
"""

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.catalog import CustomerPreferredProduct
from crm_api.models.customer import Tenant
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceList,
    PriceListItem,
    PriceListStatus,
)
from crm_api.models.tax import IcmsRule
from crm_api.models.user import User
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.icms import IcmsRuleRepository
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.services.price_publication import PricePublicationService

BASE = "/internal/representative/by-whatsapp"
TELEFONE_A = "+5511987654321"  # representante A, titular do cliente A
TELEFONE_B = "+5511955553333"  # representante B, titular do cliente B
TELEFONE_ADMIN = "+5511955552222"
TELEFONE_CLIENTE = "+5511988887777"
COMPETENCIA = date.today().replace(day=1)
ONTEM = datetime.now(UTC) - timedelta(days=1)


@pytest_asyncio.fixture
async def world():
    mundo = await build_portal_world()
    async with mundo.app.state.session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == mundo.tenant_id))
        tenant.origin_state_code = "SP"

        for user_id, telefone in (
            (mundo.representative_a_id, TELEFONE_A),
            (mundo.representative_b_id, TELEFONE_B),
            (mundo.admin_id, TELEFONE_ADMIN),
        ):
            usuario = await session.get(User, user_id)
            usuario.whatsapp_e164 = telefone

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

        lote = PriceList(
            id=uuid4(),
            tenant_id=mundo.tenant_id,
            name="Tabela do mês",
            reference_month=COMPETENCIA,
            valid_from=ONTEM,
            base_tax_rate=Decimal("18.000"),
            status=PriceListStatus.DRAFT,
        )
        session.add(lote)
        session.add(
            PriceListItem(
                id=uuid4(),
                tenant_id=mundo.tenant_id,
                price_list_id=lote.id,
                product_id=mundo.product_id,
                base_price=Decimal("12.0500"),
                availability=AvailabilityStatus.AVAILABLE,
            )
        )
        await session.commit()

        await PricePublicationService(
            session=session,
            entries=PriceEntryRepository(session),
            audit=AuditRepository(session),
        ).publish_batch(tenant_id=mundo.tenant_id, batch_id=lote.id)

        # O cliente A já nasce com o preferido no `build_portal_world`; só o B
        # precisa do seu, para que a carteira do representante B também tenha
        # tabela e o teste de escopo compare coisas equivalentes.
        session.add(
            CustomerPreferredProduct(
                id=uuid4(),
                tenant_id=mundo.tenant_id,
                customer_id=mundo.customer_b_id,
                product_id=mundo.product_id,
            )
        )
        IcmsRuleRepository(session).add(
            IcmsRule(
                id=uuid4(),
                tenant_id=mundo.tenant_id,
                origin_state="SP",
                destination_state="SP",
                tax_rate=Decimal("18.000"),
                valid_from=ONTEM,
            )
        )
        await session.commit()

    yield mundo
    await mundo.app.state.engine.dispose()


def _headers(path: str, *, secret: bytes = b"test-secret") -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join([timestamp.encode(), b"GET", path.encode(), b""])
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(secret, canonical, hashlib.sha256).hexdigest(),
    }


@asynccontextmanager
async def _cliente(world):
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://testserver"
    ) as client:
        yield client


async def _get(world, path: str, *, params: dict | None = None, secret: bytes = b"test-secret"):
    async with _cliente(world) as client:
        return await client.get(path, params=params, headers=_headers(path, secret=secret))


# ----------------------------------------------------------- busca de artigo


@pytest.mark.asyncio
async def test_representante_busca_artigo_em_preco_base(world):
    resposta = await _get(
        world, f"{BASE}/{TELEFONE_A}/price-items", params={"query": "75/36"}
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["reference_month"] == COMPETENCIA.isoformat()
    assert len(corpo["items"]) == 1
    item = corpo["items"][0]
    assert item["base_price"] == "12.0500"
    # Sem cliente na pergunta não há UF de destino, logo não há conversão.
    assert item["final_price"] is None
    assert item["tax_rate"] is None


@pytest.mark.asyncio
async def test_termo_sem_correspondencia_devolve_lista_vazia(world):
    resposta = await _get(
        world, f"{BASE}/{TELEFONE_A}/price-items", params={"query": "poliéster"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["items"] == []


@pytest.mark.asyncio
async def test_contato_de_cliente_nao_alcanca_a_busca_do_representante(world):
    """Segunda tranca: o manifesto de cliente não anuncia esta ação."""
    resposta = await _get(
        world, f"{BASE}/{TELEFONE_CLIENTE}/price-items", params={"query": "75/36"}
    )
    assert resposta.status_code == 403


# --------------------------------------------------------- busca de cliente


@pytest.mark.asyncio
async def test_representante_encontra_cliente_da_propria_carteira(world):
    resposta = await _get(world, f"{BASE}/{TELEFONE_A}/customers", params={"query": "Alfa"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [m["customer_id"] for m in corpo["matches"]] == [str(world.customer_a_id)]
    assert corpo["truncated"] is False


@pytest.mark.asyncio
async def test_representante_nao_encontra_cliente_de_outra_carteira(world):
    resposta = await _get(world, f"{BASE}/{TELEFONE_B}/customers", params={"query": "Alfa"})

    assert resposta.status_code == 200
    assert resposta.json()["matches"] == []


@pytest.mark.asyncio
async def test_admin_pelo_whatsapp_tambem_ve_apenas_a_propria_carteira(world):
    """Mais restritivo que o portal, e de propósito.

    No portal o `ADMIN` enxerga o tenant inteiro. Aqui a identidade é um número
    de telefone, prova mais fraca que uma sessão com senha, e por isso recebe o
    escopo mais estreito que ainda serve.
    """
    resposta = await _get(world, f"{BASE}/{TELEFONE_ADMIN}/customers", params={"query": "Alfa"})

    assert resposta.status_code == 200
    assert resposta.json()["matches"] == []


# ------------------------------------------------------ tabela de um cliente


@pytest.mark.asyncio
async def test_representante_recebe_a_tabela_convertida_do_cliente(world):
    resposta = await _get(
        world, f"{BASE}/{TELEFONE_A}/customers/{world.customer_a_id}/price-list"
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["customer_id"] == str(world.customer_a_id)
    assert corpo["origin_state"] == "SP"
    assert corpo["destination_state"] == "SP"
    item = corpo["items"][0]
    assert item["final_price"] is not None
    assert item["tax_rate"] == "18.000"


@pytest.mark.asyncio
async def test_a_tabela_nao_carrega_o_trace_do_calculo(world):
    """O `trace` é para ser conferido numa tela, item a item."""
    resposta = await _get(
        world, f"{BASE}/{TELEFONE_A}/customers/{world.customer_a_id}/price-list"
    )
    assert "calculation_trace" not in json.dumps(resposta.json())


@pytest.mark.asyncio
async def test_cliente_de_outra_carteira_devolve_404_de_cliente(world):
    """Mesmo corpo de um `customer_id` inexistente, como no portal."""
    fora = await _get(
        world, f"{BASE}/{TELEFONE_A}/customers/{world.customer_b_id}/price-list"
    )
    inexistente = await _get(
        world, f"{BASE}/{TELEFONE_A}/customers/{uuid4()}/price-list"
    )

    assert fora.status_code == inexistente.status_code == 404
    assert fora.json() == inexistente.json()


@pytest.mark.asyncio
async def test_sem_regra_de_icms_responde_409(world):
    """A tabela existe; falta a regra fiscal para exibi-la nessa praça."""
    async with world.app.state.session_factory() as session:
        cliente_b_regra = await session.scalars(select(IcmsRule))
        for regra in cliente_b_regra:
            await session.delete(regra)
        await session.commit()

    resposta = await _get(
        world, f"{BASE}/{TELEFONE_A}/customers/{world.customer_a_id}/price-list"
    )
    assert resposta.status_code == 409


@pytest.mark.asyncio
async def test_tenant_sem_uf_de_origem_responde_422(world):
    async with world.app.state.session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == world.tenant_id))
        tenant.origin_state_code = None
        await session.commit()

    resposta = await _get(
        world, f"{BASE}/{TELEFONE_A}/customers/{world.customer_a_id}/price-list"
    )
    assert resposta.status_code == 422


# ------------------------------------------------------------------- porta


@pytest.mark.asyncio
async def test_assinatura_errada_nao_abre_a_porta(world):
    resposta = await _get(
        world,
        f"{BASE}/{TELEFONE_A}/customers",
        params={"query": "Alfa"},
        secret=b"outra",
    )
    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_representante_desativado_nao_alcanca_nada(world):
    async with world.app.state.session_factory() as session:
        usuario = await session.get(User, world.representative_a_id)
        usuario.active = False
        await session.commit()

    resposta = await _get(world, f"{BASE}/{TELEFONE_A}/customers", params={"query": "Alfa"})
    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_telefone_sem_nono_digito_resolve_o_mesmo_representante(world):
    resposta = await _get(world, f"{BASE}/+551187654321/customers", params={"query": "Alfa"})

    assert resposta.status_code == 200
    assert len(resposta.json()["matches"]) == 1
