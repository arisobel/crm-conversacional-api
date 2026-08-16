"""Conversa de representante como histórico dele (W4, ADR-022).

O caso que motiva: no instante em que o primeiro número de representante for
autorizado no painel do Gateway, ele começa a empurrar as mensagens desse
número. Antes desta etapa, cada uma virava um evento recusado e sumia.
"""

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import (
    ADMIN_EMAIL,
    REPRESENTATIVE_A_EMAIL,
    REPRESENTATIVE_B_EMAIL,
    build_portal_world,
    login,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.customer_contact import CustomerContact
from crm_api.models.interaction import CustomerInteraction
from crm_api.models.user import User

AGORA = datetime.now(UTC)
TELEFONE_REPRESENTANTE = "+5511955554444"
TELEFONE_CLIENTE = "+5511988887777"


@pytest_asyncio.fixture
async def world():
    mundo = await build_portal_world()
    async with mundo.app.state.session_factory() as session:
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
        await session.commit()
    yield mundo
    await mundo.app.state.engine.dispose()


def _corpo(*eventos: dict) -> bytes:
    return json.dumps({"interactions": list(eventos)}).encode("utf-8")


def _headers(corpo: bytes) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join([timestamp.encode(), b"POST", b"/internal/interactions", corpo])
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


def _evento(**overrides) -> dict:
    evento = {
        "external_ref": f"wamid.{uuid4()}",
        "direction": "INBOUND",
        "occurred_at": AGORA.isoformat(),
        "whatsapp_e164": TELEFONE_REPRESENTANTE,
        "summary": "bom dia",
    }
    evento.update(overrides)
    return evento


@asynccontextmanager
async def _cliente(world, email: str | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://testserver"
    ) as client:
        if email is not None:
            await login(client, email=email)
        yield client


async def _empurrar(world, *eventos: dict):
    corpo = _corpo(*eventos)
    async with _cliente(world) as client:
        return await client.post(
            "/internal/interactions", content=corpo, headers=_headers(corpo)
        )


@pytest.mark.asyncio
async def test_mensagem_de_representante_deixa_de_ser_recusada(world):
    resposta = await _empurrar(world, _evento())
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["created"] == 1
    assert corpo["rejected"] == 0


@pytest.mark.asyncio
async def test_a_conversa_fica_com_o_representante_e_sem_cliente(world):
    await _empurrar(world, _evento())

    async with world.app.state.session_factory() as session:
        gravada = (await session.scalars(select(CustomerInteraction))).one()

    assert gravada.actor_user_id == world.representative_a_id
    assert gravada.customer_id is None
    assert gravada.contact_id is None


@pytest.mark.asyncio
async def test_mensagem_de_cliente_continua_indo_para_a_ficha_do_cliente(world):
    """O caminho que já roda em produção não pode mudar de comportamento."""
    await _empurrar(world, _evento(whatsapp_e164=TELEFONE_CLIENTE))

    async with world.app.state.session_factory() as session:
        gravada = (await session.scalars(select(CustomerInteraction))).one()

    assert gravada.customer_id == world.customer_a_id
    assert gravada.actor_user_id is None
    assert gravada.contact_id is not None


@pytest.mark.asyncio
async def test_telefone_de_ninguem_continua_sendo_recusado(world):
    """Nada órfão: o motivo muda, a recusa não."""
    resposta = await _empurrar(world, _evento(whatsapp_e164="+5541900000000"))
    corpo = resposta.json()

    assert corpo["rejected"] == 1
    assert "portal user" in corpo["results"][0]["reason"]


@pytest.mark.asyncio
async def test_um_lote_misto_grava_os_dois_donos(world):
    resposta = await _empurrar(
        world,
        _evento(),
        _evento(whatsapp_e164=TELEFONE_CLIENTE),
        _evento(whatsapp_e164="+5541900000000"),
    )
    corpo = resposta.json()
    assert (corpo["created"], corpo["rejected"]) == (2, 1)

    async with world.app.state.session_factory() as session:
        gravadas = list(await session.scalars(select(CustomerInteraction)))

    assert sum(1 for linha in gravadas if linha.actor_user_id is not None) == 1
    assert sum(1 for linha in gravadas if linha.customer_id is not None) == 1


@pytest.mark.asyncio
async def test_representante_desligado_ainda_tem_a_conversa_registrada(world):
    """Mesma razão de o contato desativado continuar sendo aceito.

    A autorização no painel do Gateway sobrevive à desativação aqui (ADR-022),
    então as mensagens continuam chegando — e perdê-las seria perder justamente
    o registro do período que interessa auditar.
    """
    async with world.app.state.session_factory() as session:
        representante = await session.get(User, world.representative_a_id)
        representante.active = False
        await session.commit()

    resposta = await _empurrar(world, _evento())
    assert resposta.json()["created"] == 1


@pytest.mark.asyncio
async def test_reenviar_o_mesmo_evento_nao_duplica(world):
    evento = _evento()
    await _empurrar(world, evento)
    resposta = await _empurrar(world, evento)

    assert resposta.json()["duplicated"] == 1


@pytest.mark.asyncio
async def test_representante_le_a_propria_conversa(world):
    await _empurrar(world, _evento())

    async with _cliente(world, REPRESENTATIVE_A_EMAIL) as client:
        resposta = await client.get(
            f"/admin/users/{world.representative_a_id}/interactions"
        )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 1
    assert corpo["items"][0]["actor_user_id"] == str(world.representative_a_id)
    assert corpo["items"][0]["customer_id"] is None


@pytest.mark.asyncio
async def test_representante_nao_le_a_conversa_de_outro(world):
    async with _cliente(world, REPRESENTATIVE_B_EMAIL) as client:
        resposta = await client.get(
            f"/admin/users/{world.representative_a_id}/interactions"
        )

    assert resposta.status_code == 403


@pytest.mark.asyncio
async def test_admin_le_a_conversa_de_qualquer_um(world):
    await _empurrar(world, _evento())

    async with _cliente(world, ADMIN_EMAIL) as client:
        resposta = await client.get(
            f"/admin/users/{world.representative_a_id}/interactions"
        )

    assert resposta.status_code == 200
    assert resposta.json()["total"] == 1


@pytest.mark.asyncio
async def test_usuario_inexistente_devolve_404(world):
    async with _cliente(world, ADMIN_EMAIL) as client:
        resposta = await client.get(f"/admin/users/{uuid4()}/interactions")

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_a_conversa_do_representante_nao_aparece_na_ficha_de_cliente(world):
    await _empurrar(world, _evento())

    async with _cliente(world, ADMIN_EMAIL) as client:
        resposta = await client.get(
            f"/admin/customers/{world.customer_a_id}/interactions"
        )

    assert resposta.json()["total"] == 0
