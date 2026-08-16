"""Manifesto de capacidades por ator (W3, ADR-022).

O teste que mais importa aqui é o de contrato: a resposta é validada contra o
`business_capability_manifest_v1.schema.json` do Gateway, embutido neste
arquivo. O Gateway recusa o manifesto **inteiro** por causa de um campo — não há
aceitação parcial —, e um manifesto recusado deixa o contato sem resposta. Sem
esse teste, a divergência só apareceria no WhatsApp de alguém.
"""

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world
from httpx import ASGITransport, AsyncClient

from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import User

CAMINHO = "/api/integrations/whatsapp/v1/capabilities/manifest"
TELEFONE_REPRESENTANTE = "+5511955554444"
TELEFONE_CLIENTE = "+5511988887777"
TELEFONE_DESCONHECIDO = "+5541900000000"

# Espelho do schema do Gateway (e122bb6). O que importa é o que ele **recusa**:
# chave desconhecida em qualquer nível, actor.id fora de 24 hexadecimais,
# expiração acima de 900 e id diferente de action.
_TOPO = {
    "schema_version",
    "provider",
    "actor",
    "channel_context",
    "expires_in_seconds",
    "capabilities",
    "help_message",
}
_CAPACIDADE = {
    "id",
    "action",
    "mode",
    "requires_confirmation",
    "idempotency",
    "title",
    "description",
    "vocabulary",
    "slots",
}
_ACOES_REGISTRADAS = {"GET_CURRENT_PRICE_LIST", "SEARCH_CURRENT_PRICE_LIST_ITEMS"}
_TIPOS_REGISTRADOS = {"product_code"}


def valida_como_o_gateway(manifesto: dict) -> None:
    """Reproduz `isValidCkjCapabilityManifest`, generalizada por provider."""
    assert set(manifesto) <= _TOPO
    assert set(manifesto) == _TOPO, "todo campo do topo é obrigatório"
    assert manifesto["schema_version"] == "business-capability-manifest/v1"
    assert manifesto["provider"] == "crm_api"

    ator = manifesto["actor"]
    assert set(ator) == {"id", "role"}
    assert len(ator["id"]) == 24
    assert all(c in "0123456789abcdef" for c in ator["id"])
    assert isinstance(ator["role"], str) and ator["role"]

    contexto = manifesto["channel_context"]
    assert set(contexto) <= {"channel", "line_phone_number_id"}
    assert contexto["channel"] == "whatsapp"
    if contexto.get("line_phone_number_id") is not None:
        assert contexto["line_phone_number_id"].isdigit()
        assert 5 <= len(contexto["line_phone_number_id"]) <= 64

    assert isinstance(manifesto["expires_in_seconds"], int)
    assert 1 <= manifesto["expires_in_seconds"] <= 900
    assert 0 < len(manifesto["help_message"]) <= 1000

    ids = []
    for capacidade in manifesto["capabilities"]:
        assert set(capacidade) <= _CAPACIDADE
        assert capacidade["id"] == capacidade["action"]
        assert capacidade["action"] in _ACOES_REGISTRADAS
        assert capacidade["mode"] in {"read", "write"}
        assert isinstance(capacidade["requires_confirmation"], bool)
        assert capacidade["idempotency"] in {"none", "required"}
        assert 0 < len(capacidade["title"]) <= 160
        assert 0 < len(capacidade["description"]) <= 500
        if capacidade["mode"] == "write":
            assert capacidade["requires_confirmation"]
            assert capacidade["idempotency"] == "required"

        vocabulario = capacidade.get("vocabulary")
        if vocabulario is not None:
            assert set(vocabulario) <= {"aliases", "examples"}
            assert len(vocabulario.get("aliases", [])) <= 32
            assert len(vocabulario.get("examples", [])) <= 16
            assert all(0 < len(a.strip()) <= 80 for a in vocabulario.get("aliases", []))
            assert all(0 < len(e.strip()) <= 240 for e in vocabulario.get("examples", []))

        slots = capacidade.get("slots")
        if slots is not None:
            assert len(slots) <= 16
            assert len({s["id"] for s in slots}) == len(slots)
            for slot in slots:
                assert set(slot) <= {"id", "required", "kind"}
                assert isinstance(slot["required"], bool)
                if slot.get("kind") is not None:
                    assert slot["kind"] in _TIPOS_REGISTRADOS

        ids.append(capacidade["id"])
    assert len(set(ids)) == len(ids)


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


def _assinado(corpo: bytes, *, secret: bytes = b"test-secret") -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join([timestamp.encode(), b"POST", CAMINHO.encode(), corpo])
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(secret, canonical, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


@asynccontextmanager
async def _cliente(world):
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://testserver"
    ) as client:
        yield client


async def _pedir(world, telefone: str, *, secret: bytes = b"test-secret"):
    corpo = json.dumps(
        {
            "contact_phone_e164": telefone,
            "channel_context": {"channel": "whatsapp", "line_phone_number_id": "1234567890"},
        }
    ).encode("utf-8")
    async with _cliente(world) as client:
        return await client.post(CAMINHO, content=corpo, headers=_assinado(corpo, secret=secret))


# ------------------------------------------------------------------ contrato


@pytest.mark.asyncio
async def test_manifesto_do_cliente_passa_no_validador_do_gateway(world):
    resposta = await _pedir(world, TELEFONE_CLIENTE)
    assert resposta.status_code == 200
    valida_como_o_gateway(resposta.json())


@pytest.mark.asyncio
async def test_manifesto_do_representante_passa_no_validador_do_gateway(world):
    resposta = await _pedir(world, TELEFONE_REPRESENTANTE)
    assert resposta.status_code == 200
    valida_como_o_gateway(resposta.json())


# --------------------------------------------------------------- por ator


@pytest.mark.asyncio
async def test_cliente_recebe_as_duas_capacidades_de_hoje(world):
    corpo = (await _pedir(world, TELEFONE_CLIENTE)).json()

    assert corpo["actor"]["role"] == "cliente"
    assert [c["action"] for c in corpo["capabilities"]] == [
        "GET_CURRENT_PRICE_LIST",
        "SEARCH_CURRENT_PRICE_LIST_ITEMS",
    ]


@pytest.mark.asyncio
async def test_representante_nao_recebe_capacidade_de_cliente(world):
    """O ponto inteiro do trabalho.

    Antes disto, o representante receberia as capacidades do cliente e os
    executores responderiam que não há tabela para o cadastro dele.
    """
    corpo = (await _pedir(world, TELEFONE_REPRESENTANTE)).json()

    assert corpo["actor"]["role"] == "representante"
    assert corpo["capabilities"] == []
    assert "portal" in corpo["help_message"]


@pytest.mark.asyncio
async def test_os_dois_atores_recebem_apelidos_diferentes(world):
    do_cliente = (await _pedir(world, TELEFONE_CLIENTE)).json()["actor"]["id"]
    do_representante = (await _pedir(world, TELEFONE_REPRESENTANTE)).json()["actor"]["id"]

    assert do_cliente != do_representante


@pytest.mark.asyncio
async def test_o_apelido_nao_muda_entre_chamadas(world):
    """Estabilidade é o motivo de ele ser sorteado e guardado (ADR-023).

    O Gateway usa o `actor.id` como chave de cache e o persiste nas observações
    sanitizadas do painel; um identificador que mudasse a cada leitura partiria
    esse histórico em dois.
    """
    primeiro = (await _pedir(world, TELEFONE_CLIENTE)).json()["actor"]["id"]
    segundo = (await _pedir(world, TELEFONE_CLIENTE)).json()["actor"]["id"]

    assert primeiro == segundo


@pytest.mark.asyncio
async def test_representante_expira_antes_do_cliente(world):
    do_cliente = (await _pedir(world, TELEFONE_CLIENTE)).json()
    do_representante = (await _pedir(world, TELEFONE_REPRESENTANTE)).json()

    assert do_representante["expires_in_seconds"] < do_cliente["expires_in_seconds"]
    assert do_cliente["expires_in_seconds"] <= 900


# ---------------------------------------------------------------- resolução


@pytest.mark.asyncio
async def test_telefone_sem_nono_digito_resolve_o_mesmo_ator(world):
    resposta = await _pedir(world, "+551188887777")

    assert resposta.status_code == 200
    assert resposta.json()["actor"]["role"] == "cliente"


@pytest.mark.asyncio
async def test_telefone_de_ninguem_devolve_404(world):
    assert (await _pedir(world, TELEFONE_DESCONHECIDO)).status_code == 404


@pytest.mark.asyncio
async def test_representante_desativado_nao_recebe_manifesto(world):
    async with world.app.state.session_factory() as session:
        representante = await session.get(User, world.representative_a_id)
        representante.active = False
        await session.commit()

    assert (await _pedir(world, TELEFONE_REPRESENTANTE)).status_code == 404


@pytest.mark.asyncio
async def test_colisao_falha_fechada_com_409(world):
    """Cadastro anterior à W1 poderia ter as duas pontas no mesmo número."""
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerContact(
                id=uuid4(),
                tenant_id=world.tenant_id,
                customer_id=world.customer_b_id,
                name="Conflito",
                whatsapp_e164=TELEFONE_REPRESENTANTE,
            )
        )
        await session.commit()

    assert (await _pedir(world, TELEFONE_REPRESENTANTE)).status_code == 409


@pytest.mark.asyncio
async def test_telefone_invalido_devolve_422(world):
    assert (await _pedir(world, "+5511")).status_code == 422


# ------------------------------------------------------------------ porta


@pytest.mark.asyncio
async def test_assinatura_errada_nao_abre_a_porta(world):
    assert (await _pedir(world, TELEFONE_CLIENTE, secret=b"outra")).status_code == 401


@pytest.mark.asyncio
async def test_sem_assinatura_nao_abre_a_porta(world):
    async with _cliente(world) as client:
        resposta = await client.post(
            CAMINHO,
            json={
                "contact_phone_e164": TELEFONE_CLIENTE,
                "channel_context": {"channel": "whatsapp"},
            },
        )
    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_campo_desconhecido_no_pedido_e_recusado(world):
    corpo = json.dumps(
        {
            "contact_phone_e164": TELEFONE_CLIENTE,
            "channel_context": {"channel": "whatsapp"},
            "line_id": "não pertence ao contrato",
        }
    ).encode("utf-8")
    async with _cliente(world) as client:
        resposta = await client.post(CAMINHO, content=corpo, headers=_assinado(corpo))

    assert resposta.status_code == 422


@pytest.mark.asyncio
async def test_o_manifesto_legado_continua_intocado(world):
    """Ele roda em produção e só sai quando a flag virar no Gateway."""
    async with _cliente(world) as client:
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        caminho = "/internal/interaction-capabilities"
        canonical = b".".join([timestamp.encode(), b"GET", caminho.encode(), b""])
        resposta = await client.get(
            caminho,
            headers={
                "X-Tenant-Slug": "test-tenant",
                "X-Timestamp": timestamp,
                "X-Signature": hmac.new(
                    b"test-secret", canonical, hashlib.sha256
                ).hexdigest(),
            },
        )

    corpo = resposta.json()
    assert resposta.status_code == 200
    assert corpo["provider"] == "crm_api"
    assert corpo["session_ttl_seconds"] == 1800
    assert [i["id"] for i in corpo["intents"]] == ["LIST_CURRENT_PRICES", "SEARCH_PRODUCT"]
