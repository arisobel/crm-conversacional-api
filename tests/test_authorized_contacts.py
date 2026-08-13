"""Roster de contatos autorizados que o Gateway espelha.

O Gateway deduz desativação por ausência, então a integridade da lista importa
mais que o desempenho: ou ela vem inteira, ou não vem.
"""

import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world
from httpx import ASGITransport, AsyncClient

from crm_api.models.customer_contact import CustomerContact

CAMINHO = "/internal/authorized-contacts"
TELEFONE_ATIVO = "+5511988887777"
TELEFONE_OUTRO_ATIVO = "+5511911112222"
TELEFONE_DESATIVADO = "+5551977776666"


@pytest_asyncio.fixture
async def world():
    mundo = await build_portal_world()
    async with mundo.app.state.session_factory() as session:
        session.add_all(
            [
                CustomerContact(
                    id=uuid4(),
                    tenant_id=mundo.tenant_id,
                    customer_id=mundo.customer_a_id,
                    name="Compras Alfa",
                    whatsapp_e164=TELEFONE_ATIVO,
                    is_primary=True,
                ),
                CustomerContact(
                    id=uuid4(),
                    tenant_id=mundo.tenant_id,
                    customer_id=mundo.customer_b_id,
                    name="Compras Beta",
                    whatsapp_e164=TELEFONE_OUTRO_ATIVO,
                    is_primary=True,
                ),
                CustomerContact(
                    id=uuid4(),
                    tenant_id=mundo.tenant_id,
                    customer_id=mundo.customer_b_id,
                    name="Ex-comprador Beta",
                    whatsapp_e164=TELEFONE_DESATIVADO,
                    active=False,
                ),
            ]
        )
        await session.commit()
    return mundo


def _headers(*, secret: bytes = b"test-secret") -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join([timestamp.encode(), b"GET", CAMINHO.encode(), b""])
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(secret, canonical, hashlib.sha256).hexdigest(),
    }


@asynccontextmanager
async def _cliente(world):
    transport = ASGITransport(app=world.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_roster_traz_somente_contatos_ativos_e_apenas_o_telefone(world):
    async with _cliente(world) as client:
        resposta = await client.get(CAMINHO, headers=_headers())

    assert resposta.status_code == 200
    corpo = resposta.json()
    # Ordenado: é o que torna o etag comparável entre duas leituras.
    assert corpo["contacts"] == sorted([TELEFONE_ATIVO, TELEFONE_OUTRO_ATIVO])
    assert corpo["count"] == 2
    # Contato desativado no CRM não pode continuar sendo atendido pelo Gateway.
    assert TELEFONE_DESATIVADO not in corpo["contacts"]
    # Nome, cliente e localidade continuam do lado do CRM.
    assert set(corpo) == {"contacts", "count", "etag", "generated_at"}


@pytest.mark.asyncio
async def test_etag_muda_quando_um_contato_e_desativado(world):
    async with _cliente(world) as client:
        antes = (await client.get(CAMINHO, headers=_headers())).json()

        async with world.app.state.session_factory() as session:
            contato = CustomerContact(
                id=uuid4(),
                tenant_id=world.tenant_id,
                customer_id=world.customer_a_id,
                name="Novo comprador",
                whatsapp_e164="+5511900009999",
            )
            session.add(contato)
            await session.commit()

        depois = (await client.get(CAMINHO, headers=_headers())).json()

    assert antes["etag"] != depois["etag"]
    # Duas leituras sem alteração precisam produzir o mesmo digest, senão a
    # reconciliação nunca poderia ser pulada.
    async with _cliente(world) as client:
        repetida = (await client.get(CAMINHO, headers=_headers())).json()
    assert repetida["etag"] == depois["etag"]


@pytest.mark.asyncio
async def test_roster_exige_hmac_valido(world):
    async with _cliente(world) as client:
        sem_assinatura = await client.get(CAMINHO)
        assinatura_errada = await client.get(CAMINHO, headers=_headers(secret=b"outro"))

    assert sem_assinatura.status_code == 401
    assert assinatura_errada.status_code == 401


# ------------------------------------------------------------ forma canônica


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("+5511988887777", "+5511988887777"),
        ("+55 (11) 98888-7777", "+5511988887777"),
        # Celular na forma anterior à renumeração: mesma pessoa, outra grafia.
        ("+551188887777", "+5511988887777"),
        # Fixo permanece com oito dígitos — WhatsApp Business pode usar linha fixa.
        ("+551133334444", "+551133334444"),
        # Fora do Brasil a regra não se aplica, mesmo com a mesma contagem.
        ("+3519123456789", "+3519123456789"),
    ],
)
def test_canoniza_telefone_para_uma_forma_unica(entrada, esperado):
    from crm_api.services.customers import normalize_whatsapp_e164

    assert normalize_whatsapp_e164(entrada) == esperado


def test_recusa_numero_sem_codigo_de_pais():
    from crm_api.services.customers import (
        InvalidWhatsappNumber,
        normalize_whatsapp_e164,
    )

    with pytest.raises(InvalidWhatsappNumber):
        normalize_whatsapp_e164("11988887777")
