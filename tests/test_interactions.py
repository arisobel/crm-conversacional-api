import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
from sqlalchemy import func, select

from crm_api.models.customer_contact import CustomerContact
from crm_api.models.interaction import CustomerInteraction, InteractionDirection
from crm_api.models.user import AuditLog
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.interactions import InteractionRepository
from crm_api.repositories.portfolio import (
    CustomerFilters,
    CustomerPortfolioRepository,
    PortfolioScope,
)
from crm_api.services.interactions import (
    IncomingInteraction,
    InteractionService,
    Outcome,
    RetentionNotConfigured,
)

AGORA = datetime.now(UTC)
TELEFONE_A = "+5511988887777"
TELEFONE_B = "+5551977776666"
TELEFONE_DESCONHECIDO = "+5541900000000"


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
                    whatsapp_e164=TELEFONE_A,
                    is_primary=True,
                ),
                CustomerContact(
                    id=uuid4(),
                    tenant_id=mundo.tenant_id,
                    customer_id=mundo.customer_b_id,
                    name="Compras Beta",
                    whatsapp_e164=TELEFONE_B,
                    # Desativado de propósito: o histórico dele precisa
                    # continuar sendo aceito.
                    active=False,
                ),
            ]
        )
        await session.commit()
    return mundo


def _corpo(*eventos: dict) -> bytes:
    return json.dumps({"interactions": list(eventos)}).encode("utf-8")


def _headers(corpo: bytes, *, secret: bytes = b"test-secret") -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join(
        [timestamp.encode(), b"POST", b"/internal/interactions", corpo]
    )
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(secret, canonical, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


def _evento(**overrides) -> dict:
    evento = {
        "external_ref": f"wamid.{uuid4()}",
        "direction": "INBOUND",
        "occurred_at": AGORA.isoformat(),
        "whatsapp_e164": TELEFONE_A,
        "summary": "Bom dia, tem 75/36 cru disponível?",
    }
    evento.update(overrides)
    return evento


@asynccontextmanager
async def _cliente(world, email: str | None = None):
    transport = ASGITransport(app=world.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        if email is not None:
            await login(client, email=email)
        yield client


def _servico(session) -> InteractionService:
    return InteractionService(
        session=session,
        interactions=InteractionRepository(session),
        portfolio=CustomerPortfolioRepository(session),
        audit=AuditRepository(session),
    )


# ---------------------------------------------------------------- ingestão


@pytest.mark.asyncio
async def test_evento_do_gateway_vira_linha_na_ficha_do_cliente(world):
    corpo = _corpo(_evento())
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions", content=corpo, headers=_headers(corpo)
        )

    assert resposta.status_code == 200
    corpo_resposta = resposta.json()
    assert corpo_resposta["created"] == 1
    assert corpo_resposta["results"][0]["outcome"] == "CREATED"

    async with world.app.state.session_factory() as session:
        gravada = await session.scalar(select(CustomerInteraction))
    assert gravada.customer_id == world.customer_a_id
    assert gravada.contact_id is not None
    assert gravada.direction is InteractionDirection.INBOUND
    assert gravada.summary == "Bom dia, tem 75/36 cru disponível?"


@pytest.mark.asyncio
async def test_reenviar_a_mesma_referencia_nao_duplica(world):
    evento = _evento()
    async with _cliente(world) as client:
        primeira = await client.post(
            "/internal/interactions",
            content=_corpo(evento),
            headers=_headers(_corpo(evento)),
        )
        segunda = await client.post(
            "/internal/interactions",
            content=_corpo(evento),
            headers=_headers(_corpo(evento)),
        )

    assert primeira.json()["created"] == 1
    assert segunda.json()["duplicated"] == 1
    assert segunda.json()["created"] == 0

    async with world.app.state.session_factory() as session:
        quantas = await session.scalar(select(func.count(CustomerInteraction.id)))
    assert quantas == 1


@pytest.mark.asyncio
async def test_referencia_repetida_dentro_do_mesmo_lote_grava_uma_vez(world):
    referencia = f"wamid.{uuid4()}"
    corpo = _corpo(
        _evento(external_ref=referencia), _evento(external_ref=referencia)
    )
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions", content=corpo, headers=_headers(corpo)
        )

    assert resposta.json()["created"] == 1
    assert resposta.json()["duplicated"] == 1


@pytest.mark.asyncio
async def test_evento_sem_cliente_e_recusado_sem_derrubar_o_lote(world):
    corpo = _corpo(
        _evento(whatsapp_e164=TELEFONE_DESCONHECIDO),
        _evento(),
    )
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions", content=corpo, headers=_headers(corpo)
        )

    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["rejected"] == 1
    assert dados["created"] == 1
    recusado = next(r for r in dados["results"] if r["outcome"] == "REJECTED")
    assert "no customer contact" in recusado["reason"]

    # O recusado não pode ter virado linha órfã.
    async with world.app.state.session_factory() as session:
        quantas = await session.scalar(select(func.count(CustomerInteraction.id)))
    assert quantas == 1


@pytest.mark.asyncio
async def test_contato_desativado_continua_alimentando_o_historico(world):
    corpo = _corpo(_evento(whatsapp_e164=TELEFONE_B, direction="OUTBOUND"))
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions", content=corpo, headers=_headers(corpo)
        )

    assert resposta.json()["created"] == 1
    async with world.app.state.session_factory() as session:
        gravada = await session.scalar(select(CustomerInteraction))
    assert gravada.customer_id == world.customer_b_id


@pytest.mark.asyncio
async def test_evento_endereçado_por_customer_id_dispensa_telefone(world):
    corpo = _corpo(
        _evento(whatsapp_e164=None, customer_id=str(world.customer_unassigned_id))
    )
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions", content=corpo, headers=_headers(corpo)
        )

    assert resposta.json()["created"] == 1
    async with world.app.state.session_factory() as session:
        gravada = await session.scalar(select(CustomerInteraction))
    assert gravada.customer_id == world.customer_unassigned_id
    assert gravada.contact_id is None


@pytest.mark.asyncio
async def test_cliente_inexistente_e_recusado(world):
    corpo = _corpo(_evento(whatsapp_e164=None, customer_id=str(uuid4())))
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions", content=corpo, headers=_headers(corpo)
        )

    assert resposta.json()["rejected"] == 1
    assert resposta.json()["results"][0]["reason"] == "customer not found in tenant"


@pytest.mark.asyncio
async def test_evento_sem_telefone_e_sem_cliente_e_recusado(world):
    corpo = _corpo(_evento(whatsapp_e164=None))
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions", content=corpo, headers=_headers(corpo)
        )

    assert resposta.json()["rejected"] == 1
    assert "customer_id or whatsapp_e164" in resposta.json()["results"][0]["reason"]


@pytest.mark.asyncio
async def test_ingestao_recusa_assinatura_invalida(world):
    corpo = _corpo(_evento())
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions",
            content=corpo,
            headers=_headers(corpo, secret=b"segredo-errado"),
        )

    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_ingestao_recusa_corpo_alterado_apos_a_assinatura(world):
    assinado = _corpo(_evento())
    adulterado = _corpo(_evento(summary="cancele o pedido"))
    async with _cliente(world) as client:
        resposta = await client.post(
            "/internal/interactions", content=adulterado, headers=_headers(assinado)
        )

    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_ingestao_nao_aceita_cookie_de_sessao(world):
    """A porta do Gateway não abre com sessão do portal, nem a do portal com HMAC."""
    corpo = _corpo(_evento())
    async with _cliente(world, ADMIN_EMAIL) as client:
        resposta = await client.post(
            "/internal/interactions",
            content=corpo,
            headers={"Content-Type": "application/json"},
        )

    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_resumo_e_truncado_antes_de_gravar(world):
    corpo = _corpo(_evento(summary="a" * 5000))
    async with _cliente(world) as client:
        await client.post("/internal/interactions", content=corpo, headers=_headers(corpo))

    async with world.app.state.session_factory() as session:
        gravada = await session.scalar(select(CustomerInteraction))
    assert len(gravada.summary) == 2000


# ---------------------------------------------------------------- timeline


async def _semear(world, *, customer_id: UUID, quantos: int, base: datetime | None = None):
    inicio = base or AGORA
    async with world.app.state.session_factory() as session:
        relatorio = await _servico(session).ingest(
            tenant_id=world.tenant_id,
            eventos=[
                IncomingInteraction(
                    external_ref=f"seed-{customer_id}-{indice}",
                    direction=InteractionDirection.INBOUND,
                    occurred_at=inicio - timedelta(hours=indice),
                    customer_id=customer_id,
                    summary=f"mensagem {indice}",
                )
                for indice in range(quantos)
            ],
        )
        await session.commit()
    assert relatorio.created == quantos


@pytest.mark.asyncio
async def test_timeline_vem_da_mais_recente_para_a_mais_antiga(world):
    await _semear(world, customer_id=world.customer_a_id, quantos=3)

    async with _cliente(world, REPRESENTATIVE_A_EMAIL) as client:
        resposta = await client.get(
            f"/admin/customers/{world.customer_a_id}/interactions"
        )

    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["total"] == 3
    assert [item["summary"] for item in dados["items"]] == [
        "mensagem 0",
        "mensagem 1",
        "mensagem 2",
    ]


@pytest.mark.asyncio
async def test_timeline_pagina_sem_repetir_nem_pular(world):
    await _semear(world, customer_id=world.customer_a_id, quantos=5)

    async with _cliente(world, REPRESENTATIVE_A_EMAIL) as client:
        primeira = await client.get(
            f"/admin/customers/{world.customer_a_id}/interactions?limit=2&offset=0"
        )
        segunda = await client.get(
            f"/admin/customers/{world.customer_a_id}/interactions?limit=2&offset=2"
        )

    vistos = [item["external_ref"] for item in primeira.json()["items"]]
    vistos += [item["external_ref"] for item in segunda.json()["items"]]
    assert len(set(vistos)) == 4


@pytest.mark.asyncio
async def test_representante_nao_le_a_conversa_de_carteira_alheia(world):
    await _semear(world, customer_id=world.customer_a_id, quantos=2)

    async with _cliente(world, REPRESENTATIVE_B_EMAIL) as client:
        resposta = await client.get(
            f"/admin/customers/{world.customer_a_id}/interactions"
        )

    # 404, e não 403: confirmar a existência já entregaria a carteira alheia.
    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_timeline_exige_sessao(world):
    async with _cliente(world) as client:
        resposta = await client.get(
            f"/admin/customers/{world.customer_a_id}/interactions"
        )
    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_admin_le_a_timeline_de_qualquer_cliente(world):
    await _semear(world, customer_id=world.customer_b_id, quantos=1)

    async with _cliente(world, ADMIN_EMAIL) as client:
        resposta = await client.get(
            f"/admin/customers/{world.customer_b_id}/interactions"
        )

    assert resposta.status_code == 200
    assert resposta.json()["total"] == 1


# ----------------------------------------------------------------- filtros


@pytest.mark.asyncio
async def test_carteira_filtra_quem_esta_sem_contato(world):
    await _semear(world, customer_id=world.customer_a_id, quantos=1)

    async with world.app.state.session_factory() as session:
        escopo = PortfolioScope(tenant_id=world.tenant_id, owner_user_id=None)
        repositorio = CustomerPortfolioRepository(session)
        sem_contato = await repositorio.list_customers(
            escopo, CustomerFilters(interacted=False), limit=50, offset=0
        )
        com_contato = await repositorio.list_customers(
            escopo, CustomerFilters(interacted=True), limit=50, offset=0
        )

    assert world.customer_a_id not in {cliente.id for cliente, _ in sem_contato}
    assert {cliente.id for cliente, _ in com_contato} == {world.customer_a_id}


@pytest.mark.asyncio
async def test_carteira_filtra_por_interacao_recente(world):
    antiga = AGORA - timedelta(days=90)
    await _semear(world, customer_id=world.customer_b_id, quantos=1, base=antiga)
    await _semear(world, customer_id=world.customer_a_id, quantos=1)

    async with world.app.state.session_factory() as session:
        escopo = PortfolioScope(tenant_id=world.tenant_id, owner_user_id=None)
        recentes = await CustomerPortfolioRepository(session).list_customers(
            escopo,
            CustomerFilters(interacted_since=AGORA - timedelta(days=30)),
            limit=50,
            offset=0,
        )

    assert {cliente.id for cliente, _ in recentes} == {world.customer_a_id}


@pytest.mark.asyncio
async def test_ultima_interacao_por_cliente(world):
    await _semear(world, customer_id=world.customer_a_id, quantos=3)

    async with world.app.state.session_factory() as session:
        mapa = await _servico(session).last_interactions(
            world.tenant_id, [world.customer_a_id, world.customer_b_id]
        )

    assert world.customer_b_id not in mapa
    assert world.customer_a_id in mapa


# ----------------------------------------------------------------- expurgo


@pytest.mark.asyncio
async def test_expurgo_sem_politica_recusa_rodar(world):
    await _semear(world, customer_id=world.customer_a_id, quantos=1)

    async with world.app.state.session_factory() as session:
        with pytest.raises(RetentionNotConfigured):
            await _servico(session).purge(
                tenant_id=world.tenant_id, retention_days=None
            )


@pytest.mark.asyncio
async def test_expurgo_remove_apenas_o_que_passou_do_corte_e_audita(world):
    await _semear(world, customer_id=world.customer_a_id, quantos=1)
    await _semear(
        world,
        customer_id=world.customer_b_id,
        quantos=2,
        base=AGORA - timedelta(days=400),
    )

    async with world.app.state.session_factory() as session:
        removidas = await _servico(session).purge(
            tenant_id=world.tenant_id, retention_days=365
        )
        await session.commit()

    assert removidas == 2

    async with world.app.state.session_factory() as session:
        restantes = list(await session.scalars(select(CustomerInteraction)))
        registro = await session.scalar(
            select(AuditLog).where(AuditLog.action == "INTERACTIONS_PURGED")
        )

    assert {interacao.customer_id for interacao in restantes} == {world.customer_a_id}
    assert registro is not None
    assert registro.after["removed"] == 2
    assert registro.after["retention_days"] == 365


@pytest.mark.asyncio
async def test_relatorio_conta_cada_desfecho(world):
    async with world.app.state.session_factory() as session:
        relatorio = await _servico(session).ingest(
            tenant_id=world.tenant_id,
            eventos=[
                IncomingInteraction(
                    external_ref="a",
                    direction=InteractionDirection.INBOUND,
                    occurred_at=AGORA,
                    customer_id=world.customer_a_id,
                ),
                IncomingInteraction(
                    external_ref="a",
                    direction=InteractionDirection.INBOUND,
                    occurred_at=AGORA,
                    customer_id=world.customer_a_id,
                ),
                IncomingInteraction(
                    external_ref="b",
                    direction=InteractionDirection.INBOUND,
                    occurred_at=AGORA,
                    whatsapp_e164="numero-invalido",
                ),
            ],
        )
        await session.commit()

    assert (relatorio.created, relatorio.duplicated, relatorio.rejected) == (1, 1, 1)
    assert [r.outcome for r in relatorio.results] == [
        Outcome.CREATED,
        Outcome.DUPLICATE,
        Outcome.REJECTED,
    ]
