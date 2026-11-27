import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from conftest import (
    ADMIN_EMAIL,
    PASSWORD,
    REPRESENTATIVE_A_EMAIL,
    build_portal_world,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.assistant_settings import (
    AssistantRepresentativeSettings,
    ConversationBehaviorSettings,
    ConversationSimulationScenario,
    MvpReleaseControl,
)
from crm_api.models.customer import Customer, CustomerFact, CustomerLocation
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.customer_intake import CustomerIntake
from crm_api.models.interaction import (
    GATEWAY_SOURCE,
    CustomerInteraction,
    InteractionDirection,
    InteractionKind,
)
from crm_api.models.reminder import ReminderOrigin, ReminderStatus, RepresentativeReminder
from crm_api.models.user import AuditLog, User
from crm_api.models.whatsapp_connection import (
    RepresentativeWhatsappConnection,
    WhatsappConnectionStatus,
)
from crm_api.services.gateway_whatsapp_onboarding import (
    GatewaySimulationResult,
    GatewayWhatsappOnboardingClient,
)

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    yield built
    await built.app.state.engine.dispose()


@asynccontextmanager
async def _browser(world):
    """Cliente que segue redirecionamentos, como um navegador."""
    async with AsyncClient(
        transport=ASGITransport(app=world.app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client


def _token(html: str) -> str:
    achado = _CSRF.search(html)
    assert achado, "página não trouxe campo csrf_token"
    return achado.group(1)


async def _entrar(client, email: str, senha: str = PASSWORD):
    pagina = await client.get("/portal/login")
    return await client.post(
        "/portal/login",
        data={"email": email, "password": senha, "csrf_token": _token(pagina.text)},
    )


@pytest.mark.asyncio
async def test_ficha_registra_confirma_e_arquiva_memoria_do_cliente(world, admin):
    page = await admin.get(f"/portal/customers/{world.customer_a_id}?aba=informacoes")
    assert "Informações adicionais" in page.text

    created = await admin.post(
        f"/portal/customers/{world.customer_a_id}/facts",
        data={
            "csrf_token": _token(page.text),
            "category": "PREFERENCE",
            "fact_text": "Torce para o Santos e prefere reuniões pela manhã.",
        },
    )
    assert "Informação adicional registrada e confirmada" in created.text
    assert "Torce para o Santos" in created.text

    async with world.app.state.session_factory() as session:
        fact = await session.scalar(
            select(CustomerFact).where(CustomerFact.customer_id == world.customer_a_id)
        )
        assert fact is not None
        assert fact.status == "CONFIRMED"
        fact_id = fact.id

    archived = await admin.post(
        f"/portal/customers/{world.customer_a_id}/facts/{fact_id}",
        data={"csrf_token": _token(created.text), "acao": "arquivar"},
    )
    assert "Informação retirada da memória ativa" in archived.text
    assert "Nenhuma informação adicional confirmada" in archived.text
    async with world.app.state.session_factory() as session:
        archived_fact = await session.get(CustomerFact, fact_id)
        assert archived_fact is not None and archived_fact.active is False


@pytest.mark.asyncio
async def test_representante_nao_registra_memoria_fora_da_propria_carteira(world):
    async with _browser(world) as representative:
        await _entrar(representative, REPRESENTATIVE_A_EMAIL)
        own_page = await representative.get(
            f"/portal/customers/{world.customer_a_id}?aba=informacoes"
        )
        response = await representative.post(
            f"/portal/customers/{world.customer_b_id}/facts",
            data={
                "csrf_token": _token(own_page.text),
                "category": "OTHER",
                "fact_text": "Não deve ser gravado.",
            },
        )
    assert "/portal/customers" in str(response.url)
    async with world.app.state.session_factory() as session:
        facts = list(await session.scalars(select(CustomerFact)))
    assert facts == []


@pytest.mark.asyncio
async def test_portal_permite_assumir_atendimento_e_pausar_robo(world, admin, monkeypatch):
    captured = {}

    async def status(_client, **_payload):
        return "ASSISTANT_ACTIVE"

    async def activate(_client, **payload):
        captured.update(payload)
        return "HUMAN_HANDOFF"

    monkeypatch.setattr(GatewayWhatsappOnboardingClient, "handoff_status", status)
    monkeypatch.setattr(GatewayWhatsappOnboardingClient, "activate_handoff", activate)
    async with world.app.state.session_factory() as session:
        session.add_all(
            [
                CustomerContact(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    customer_id=world.customer_a_id,
                    name="Compras Alfa",
                    whatsapp_e164="+5511988887777",
                    is_primary=True,
                ),
                RepresentativeWhatsappConnection(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    representative_user_id=world.representative_a_id,
                    status=WhatsappConnectionStatus.CONNECTED,
                    idempotency_key="portal-handoff-a",
                    gateway_line_reference="line-a",
                    created_by_user_id=world.admin_id,
                ),
            ]
        )
        await session.commit()

    page = await admin.get(f"/portal/customers/{world.customer_a_id}")
    assert "Assumir atendimento" in page.text
    response = await admin.post(
        f"/portal/customers/{world.customer_a_id}/assistant/pause",
        data={"csrf_token": _token(page.text)},
    )

    assert "Atendimento assumido" in response.text
    assert captured["gateway_line_reference"] == "line-a"
    assert captured["contact_phone_e164"] == "+5511988887777"


@pytest_asyncio.fixture
async def admin(world):
    async with _browser(world) as client:
        resposta = await _entrar(client, ADMIN_EMAIL)
        assert resposta.status_code == 200
        yield client


@pytest.mark.asyncio
async def test_assistente_salva_configuracao_e_auditoria(world, admin):
    page = await admin.get("/portal/assistant")
    assert "As escolhas salvas aqui controlam as permissões" in page.text
    token = _token(page.text)
    await admin.post(
        "/portal/assistant/organization",
        data={
            "csrf_token": token,
            "enabled": "true",
        },
    )
    response = await admin.post(
        f"/portal/assistant/representatives/{world.representative_a_id}",
        data={"csrf_token": token, "enabled": "true", "capabilities": "CRM_REP_LOOKUP_CUSTOMER"},
    )
    assert "Configuração do assistente salva" in response.text
    async with world.app.state.session_factory() as session:
        rep = await session.get(
            AssistantRepresentativeSettings, (world.tenant_id, world.representative_a_id)
        )
        assert rep is not None and rep.enabled
        entries = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "assistant.representative.updated")
            )
        ).all()
        assert len(entries) == 1
        assert entries[0].after["capabilities"] == ["CRM_REP_LOOKUP_CUSTOMER"]


@pytest.mark.asyncio
async def test_simulador_fica_no_menu_e_nao_executa_acao(world, admin, monkeypatch):
    captured = {}

    async def simulate(_client, **payload):
        captured.update(payload)
        return GatewaySimulationResult(
            status="RESOLVED",
            reply="Entendi. Neste ensaio, nenhum dado foi consultado.",
            source="LLM",
            capability_id="CRM_REP_LOOKUP_CUSTOMER",
            capability_title="Localizar cliente",
            action="CRM_REP_LOOKUP_CUSTOMER",
            slots={"customer_query": "Aurora"},
        )

    monkeypatch.setattr(GatewayWhatsappOnboardingClient, "simulate_message", simulate)
    page = await admin.get("/portal/simulator")

    assert page.status_code == 200
    assert "Simulador de conversas" in page.text
    assert page.text.index("/portal/users") < page.text.index("/portal/simulator")
    assert page.text.index("/portal/simulator") < page.text.index("/portal/assistant")
    assert "Modo seguro" in page.text
    assert '<svg viewBox="0 0 32 32"><circle cx="16" cy="9"' in page.text

    response = await admin.post(
        "/portal/simulator",
        data={
            "csrf_token": _token(page.text),
            "mode": "CUSTOMER_SERVICE",
            "representative_id": "",
            "message": "Pode localizar o cliente Aurora?",
            "conversation_history": "[]",
        },
    )

    assert response.status_code == 200
    assert "Pedido reconhecido" in response.text
    assert "Localizar cliente" in response.text
    assert "Aurora" in response.text
    assert captured["actor_role"] == "cliente"
    assert captured["history"] == []
    assert captured["capabilities"]


@pytest.mark.asyncio
async def test_simulador_e_restrito_ao_administrador(world):
    async with _browser(world) as representative:
        await _entrar(representative, REPRESENTATIVE_A_EMAIL)
        response = await representative.get("/portal/simulator")

    assert "/portal/customers" in str(response.url)
    assert "/portal/simulator" not in response.text


@pytest.mark.asyncio
async def test_simulador_salva_e_reexecuta_cenario_sem_acao(world, admin, monkeypatch):
    calls = []

    async def simulate(_client, **payload):
        calls.append(payload)
        return GatewaySimulationResult(
            status="RESOLVED",
            reply="Entendi a preferência.",
            source="LLM",
            suggested_facts=(
                {
                    "category": "PREFERENCE",
                    "text": "Torcedor do Santos.",
                    "confidence_score": 96,
                },
            ),
        )

    monkeypatch.setattr(GatewayWhatsappOnboardingClient, "simulate_message", simulate)
    page = await admin.get("/portal/simulator")
    saved = await admin.post(
        "/portal/simulator/scenarios",
        data={
            "csrf_token": _token(page.text),
            "scenario_name": "Aprende time do cliente",
            "mode": "CUSTOMER_SERVICE",
            "representative_id": "",
            "message": "Eu torço para o Santos",
            "expected_status": "RESOLVED",
            "expected_capability_id": "",
            "expected_action": "",
            "expected_fact_text": "Torcedor do Santos.",
            "conversation_history": json.dumps(
                [
                    {"role": "user", "text": "Oi"},
                    {"role": "assistant", "text": "Como posso ajudar?"},
                ]
            ),
            "expected_reply_contains": "entendi a preferencia",
            "forbidden_reply_contains": "não entendi|envie novamente",
            "max_questions": "0",
        },
    )
    assert "Cenário de teste salvo" in saved.text

    executed = await admin.post(
        "/portal/simulator/scenarios/run",
        data={"csrf_token": _token(saved.text)},
    )
    assert "Todos os cenários de conversa foram aprovados" in executed.text
    assert "Aprovado" in executed.text
    assert len(calls) == 1
    assert calls[0]["actor_role"] == "cliente"
    assert calls[0]["history"] == [
        {"role": "user", "text": "Oi"},
        {"role": "assistant", "text": "Como posso ajudar?"},
    ]

    async with world.app.state.session_factory() as session:
        scenario = await session.scalar(select(ConversationSimulationScenario))
    assert scenario is not None
    assert len(scenario.conversation_history) == 2
    assert scenario.expected_reply_contains == "entendi a preferencia"
    assert scenario.forbidden_reply_contains == "não entendi|envie novamente"
    assert scenario.max_questions == 0
    assert scenario.last_passed is True
    assert scenario.last_run_at is not None


@pytest.mark.asyncio
async def test_simulador_reprova_resposta_robotica_ou_incompleta(world, admin, monkeypatch):
    async def simulate(_client, **_payload):
        return GatewaySimulationResult(
            status="RESOLVED",
            reply="Não entendi. Pode repetir? Quer tentar novamente?",
            source="FALLBACK",
        )

    monkeypatch.setattr(GatewayWhatsappOnboardingClient, "simulate_message", simulate)
    page = await admin.get("/portal/simulator")
    saved = await admin.post(
        "/portal/simulator/scenarios",
        data={
            "csrf_token": _token(page.text),
            "scenario_name": "Confirma o que compreendeu",
            "mode": "CUSTOMER_SERVICE",
            "representative_id": "",
            "message": "Meu contato é a Juliana",
            "expected_status": "RESOLVED",
            "expected_reply_contains": "Juliana|contato",
            "forbidden_reply_contains": "não entendi",
            "max_questions": "1",
        },
    )

    executed = await admin.post(
        "/portal/simulator/scenarios/run",
        data={"csrf_token": _token(saved.text)},
    )

    assert "Um ou mais cenários reprovaram" in executed.text
    async with world.app.state.session_factory() as session:
        scenario = await session.scalar(select(ConversationSimulationScenario))
    assert scenario is not None
    assert scenario.last_passed is False
    assert "trechos ausentes: Juliana, contato" in scenario.last_result
    assert "trechos proibidos encontrados: não entendi" in scenario.last_result
    assert "perguntas: 2 (máximo: 1)" in scenario.last_result


@pytest.mark.asyncio
async def test_central_exibe_mensagem_que_o_robo_nao_entendeu(world, admin):
    now = datetime.now(UTC)
    async with world.app.state.session_factory() as session:
        session.add_all(
            [
                CustomerInteraction(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    customer_id=world.customer_a_id,
                    kind=InteractionKind.CUSTOMER_CHANNEL,
                    direction=InteractionDirection.INBOUND,
                    source=GATEWAY_SOURCE,
                    channel="WHATSAPP",
                    external_ref="wamid.UNDERSTOOD.TEST",
                    occurred_at=now,
                    summary="Quero separar uma amostra para sexta",
                ),
                CustomerInteraction(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    customer_id=world.customer_a_id,
                    kind=InteractionKind.CUSTOMER_CHANNEL,
                    direction=InteractionDirection.OUTBOUND,
                    source=GATEWAY_SOURCE,
                    channel="WHATSAPP",
                    external_ref="wamid.UNDERSTOOD.TEST:out:1",
                    occurred_at=now,
                    summary="Pode explicar melhor o que você precisa?",
                    payload={"outcome": "RECOVERY"},
                ),
            ]
        )
        await session.commit()

    page = await admin.get("/portal/assistant/unresolved")

    assert page.status_code == 200
    assert "Quero separar uma amostra para sexta" in page.text
    assert "Pode explicar melhor" in page.text
    assert "Alfa Tecelagem" in page.text


@pytest.mark.asyncio
async def test_central_exibe_funcionamento_conversa_agenda_e_handoff(world, admin):
    now = datetime.now(UTC)
    async with world.app.state.session_factory() as session:
        session.add_all(
            [
                CustomerInteraction(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    customer_id=world.customer_a_id,
                    kind=InteractionKind.CUSTOMER_CHANNEL,
                    direction=InteractionDirection.INBOUND,
                    source=GATEWAY_SOURCE,
                    channel="WHATSAPP",
                    external_ref="wamid.MONITOR.CUSTOMER",
                    occurred_at=now,
                    summary="Mensagem do cliente",
                ),
                CustomerInteraction(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    customer_id=world.customer_a_id,
                    kind=InteractionKind.CUSTOMER_CHANNEL,
                    direction=InteractionDirection.OUTBOUND,
                    source=GATEWAY_SOURCE,
                    channel="WHATSAPP",
                    external_ref="wamid.MONITOR.CUSTOMER:out:1",
                    occurred_at=now,
                    summary="Pode explicar de outra forma?",
                    payload={"outcome": "RECOVERY"},
                ),
                CustomerInteraction(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    customer_id=world.customer_a_id,
                    kind=InteractionKind.CUSTOMER_CHANNEL,
                    direction=InteractionDirection.OUTBOUND,
                    source=GATEWAY_SOURCE,
                    channel="WHATSAPP",
                    external_ref="wamid.MONITOR.CUSTOMER:out:2",
                    occurred_at=now,
                    summary="Vou encaminhar seu pedido.",
                    payload={"outcome": "HUMAN_HANDOFF"},
                ),
                CustomerInteraction(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    actor_user_id=world.representative_a_id,
                    kind=InteractionKind.ACTOR_CHANNEL,
                    direction=InteractionDirection.INBOUND,
                    source=GATEWAY_SOURCE,
                    channel="WHATSAPP",
                    external_ref="wamid.MONITOR.REP",
                    occurred_at=now,
                    summary="Mensagem do representante",
                ),
                RepresentativeReminder(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    representative_user_id=world.representative_a_id,
                    customer_id=world.customer_a_id,
                    origin=ReminderOrigin.CUSTOMER.value,
                    kind="CALL",
                    status=ReminderStatus.CONFIRMED.value,
                    note="Ligação atrasada",
                    due_at=now - timedelta(minutes=5),
                    timezone="America/Sao_Paulo",
                    source_wamid="wamid.MONITOR.REMINDER",
                ),
                AuditLog(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    actor_user_id=world.representative_a_id,
                    action="PRICE_BATCH_PUBLISHED",
                    entity="price_lists",
                    entity_id=uuid4(),
                    after={"criados": 1},
                ),
                CustomerIntake(
                    id=uuid4(),
                    tenant_id=world.tenant_id,
                    created_by_user_id=world.representative_a_id,
                    idempotency_key="wamid.MONITOR.INTAKE",
                    legal_name="Cliente aguardando revisão",
                    created_at=now - timedelta(hours=25),
                ),
            ]
        )
        await session.commit()

    page = await admin.get("/portal/assistant")

    assert page.status_code == 200
    assert "Visão operacional" in page.text
    assert "Requer atenção" in page.text
    assert "1 aviso(s) atrasado(s)" in page.text
    assert "Transferências humanas" in page.text
    assert "Gateway WhatsApp" in page.text
    assert "Não foi possível consultar agora" in page.text
    assert "Cadastros aguardando conferência" in page.text
    assert "1 há mais de 24h" in page.text
    assert "1 pré-cadastro(s) aguarda(m) conferência há mais de 24 horas." in page.text


@pytest.mark.asyncio
async def test_gate_mvp_registra_evidencia_e_detecta_mudanca_no_escopo(world, admin):
    page = await admin.get("/portal/assistant")
    assert "Gate objetivo de entrega" in page.text
    assert "Liberação bloqueada" in page.text

    evidence = await admin.post(
        "/portal/assistant/release/checks/LINE_ROUTING",
        data={
            "csrf_token": _token(page.text),
            "status": "PASS",
            "note": "Cliente e representante testados em linhas distintas.",
        },
    )
    assert "Evidência do teste ponta a ponta registrada" in evidence.text

    frozen = await admin.post(
        "/portal/assistant/release/freeze",
        data={"csrf_token": _token(evidence.text), "scope_version": "MVP-PILOTO"},
    )
    assert "Escopo desta versão congelado" in frozen.text
    assert "Configuração atual corresponde ao escopo aprovado" in frozen.text

    changed = await admin.post(
        "/portal/assistant/behavior/COEXISTENCE",
        data={
            "csrf_token": _token(frozen.text),
            "tone": "cordial",
            "context_minutes": "180",
            "instructions": "Nova orientacao aprovada depois do congelamento.",
        },
    )
    assert "Há mudanças posteriores; revise e congele novamente" in changed.text

    async with world.app.state.session_factory() as session:
        control = await session.get(MvpReleaseControl, world.tenant_id)
        audits = list(
            await session.scalars(
                select(AuditLog.action).where(
                    AuditLog.action.in_({"mvp.acceptance_check.updated", "mvp.scope.frozen"})
                )
            )
        )
    assert control is not None
    assert control.scope_version == "MVP-PILOTO"
    assert control.acceptance_checks["LINE_ROUTING"]["status"] == "PASS"
    assert set(audits) == {"mvp.acceptance_check.updated", "mvp.scope.frozen"}


@pytest.mark.asyncio
async def test_carteira_unifica_calendario_e_cria_compromisso_manual(world, admin):
    page = await admin.get("/portal/customers")
    assert "Carteira &amp; Agenda" in page.text
    assert "Agenda e Notificações" in page.text
    assert "Novo compromisso" in page.text

    due_local = (datetime.now(UTC) + timedelta(days=2)).astimezone(ZoneInfo("America/Sao_Paulo"))
    response = await admin.post(
        "/portal/customers/reminders",
        data={
            "csrf_token": _token(page.text),
            "customer_id": str(world.customer_a_id),
            "kind": "MEETING",
            "due_local": due_local.strftime("%Y-%m-%dT%H:%M"),
            "note": "Revisar nova coleção",
        },
    )
    assert "Compromisso adicionado" in response.text

    async with world.app.state.session_factory() as session:
        reminder = await session.scalar(
            select(RepresentativeReminder).where(
                RepresentativeReminder.note == "Revisar nova coleção"
            )
        )
        assert reminder is not None
        assert reminder.origin == ReminderOrigin.REPRESENTATIVE.value
        assert reminder.status == ReminderStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_personalidade_dos_robos_e_salva_separadamente(world, admin):
    page = await admin.get("/portal/assistant")
    token = _token(page.text)
    assert "Atendimento aos clientes · Coexistence" in page.text
    for bot, tone in [("ASSISTANT", "objetivo"), ("COEXISTENCE", "cordial")]:
        result = await admin.post(
            f"/portal/assistant/behavior/{bot}",
            data={
                "csrf_token": token,
                "tone": tone,
                "context_minutes": "120",
                "instructions": f"Converse naturalmente: {bot}",
            },
        )
        assert "Configuração do assistente salva" in result.text
    async with world.app.state.session_factory() as session:
        assistant = await session.get(ConversationBehaviorSettings, (world.tenant_id, "ASSISTANT"))
        coexistence = await session.get(
            ConversationBehaviorSettings, (world.tenant_id, "COEXISTENCE")
        )
        assert assistant.tone == "objetivo"
        assert coexistence.tone == "cordial"
        assert assistant.context_minutes == coexistence.context_minutes == 120
        audit = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "conversation.behavior.updated")
            )
        ).all()
        assert len(audit) == 2


@pytest.mark.asyncio
async def test_personalidade_rejeita_valores_invalidos_e_outros_usuarios(world, admin):
    page = await admin.get("/portal/assistant")
    token = _token(page.text)
    await admin.post(
        "/portal/assistant/behavior/COEXISTENCE",
        data={
            "csrf_token": token,
            "tone": "cordial",
            "context_minutes": "1",
            "instructions": "Olá",
        },
    )
    async with _browser(world) as representative:
        page = await _entrar(representative, REPRESENTATIVE_A_EMAIL)
        await representative.post(
            "/portal/assistant/behavior/COEXISTENCE",
            data={
                "csrf_token": _token(page.text),
                "tone": "cordial",
                "context_minutes": "120",
                "instructions": "Olá",
            },
        )
    async with world.app.state.session_factory() as session:
        assert (
            await session.get(ConversationBehaviorSettings, (world.tenant_id, "COEXISTENCE"))
            is None
        )


@pytest.mark.asyncio
async def test_assistente_recusa_representante_e_capacidade_desconhecida(world, admin):
    page = await admin.get("/portal/assistant")
    token = _token(page.text)
    await admin.post(
        f"/portal/assistant/representatives/{world.representative_a_id}",
        data={
            "csrf_token": token,
            "enabled": "true",
            "capabilities": "UNKNOWN",
        },
    )
    async with world.app.state.session_factory() as session:
        assert (
            await session.get(
                AssistantRepresentativeSettings, (world.tenant_id, world.representative_a_id)
            )
            is None
        )
    async with _browser(world) as representative:
        await _entrar(representative, REPRESENTATIVE_A_EMAIL)
        page = await representative.get("/portal/assistant")
        assert "/portal/customers" in str(page.url)
        await representative.post(
            "/portal/assistant/organization",
            data={
                "csrf_token": _token(page.text),
                "enabled": "true",
            },
        )
        async with world.app.state.session_factory() as session:
            entries = (
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "assistant.organization.updated")
                )
            ).all()
            assert not entries


# ---------------------------------------------------------------- sessão


@pytest.mark.asyncio
async def test_pagina_protegida_redireciona_para_o_login(world):
    async with _browser(world) as client:
        resposta = await client.get("/portal/customers")

    assert resposta.status_code == 200
    assert str(resposta.url).endswith("/portal/login")
    assert "Portal do representante" in resposta.text


@pytest.mark.asyncio
async def test_login_leva_para_inicio(world):
    async with _browser(world) as client:
        resposta = await _entrar(client, ADMIN_EMAIL)

    assert resposta.status_code == 200
    assert "/portal/home" in str(resposta.url)
    assert "Gestora Exemplo" in resposta.text
    assert "Clientes na carteira" in resposta.text
    assert 'id="tema-toggle"' in resposta.text
    assert "Central dos robôs" in resposta.text
    assert "resumo-icone" in resposta.text


@pytest.mark.asyncio
async def test_login_errado_nao_vaza_qual_campo_falhou(world):
    async with _browser(world) as client:
        errada = await _entrar(client, ADMIN_EMAIL, "SenhaErrada12345")
        inexistente = await _entrar(client, "ninguem@teste.com.br", PASSWORD)

    assert errada.status_code == inexistente.status_code == 401
    assert "E-mail ou senha inválidos." in errada.text
    assert "E-mail ou senha inválidos." in inexistente.text


@pytest.mark.asyncio
async def test_formulario_sem_csrf_e_recusado(world):
    """Sem o token, o POST é rejeitado antes de tocar o banco."""
    async with _browser(world) as client:
        await client.get("/portal/login")
        resposta = await client.post(
            "/portal/login", data={"email": ADMIN_EMAIL, "password": PASSWORD}
        )

    assert resposta.status_code == 400
    assert "formulário expirou" in resposta.text


@pytest.mark.asyncio
async def test_csrf_de_outra_origem_nao_serve(world):
    async with _browser(world) as client:
        await client.get("/portal/login")
        resposta = await client.post(
            "/portal/login",
            data={
                "email": ADMIN_EMAIL,
                "password": PASSWORD,
                "csrf_token": "token-forjado-por-outro-site",
            },
        )

    assert resposta.status_code == 400


@pytest.mark.asyncio
async def test_logout_encerra_a_sessao(world, admin):
    pagina = await admin.get("/portal/customers")
    resposta = await admin.post("/portal/logout", data={"csrf_token": _token(pagina.text)})

    assert str(resposta.url).endswith("/portal/login")

    seguinte = await admin.get("/portal/customers")
    assert str(seguinte.url).endswith("/portal/login")


# -------------------------------------------------------------- carteira


@pytest.mark.asyncio
async def test_representante_ve_apenas_a_propria_carteira(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await client.get("/portal/customers")

    assert "Alfa Tecelagem Ltda." in resposta.text
    assert "Beta Malharia Ltda." not in resposta.text
    assert "Gama Confecções Ltda." not in resposta.text
    # Sem papel de gestão, não aparece o menu de representantes.
    assert "/portal/users" not in resposta.text


@pytest.mark.asyncio
async def test_admin_ve_todo_o_tenant(admin):
    resposta = await admin.get("/portal/customers")

    for nome in ("Alfa Tecelagem", "Beta Malharia", "Gama Confecções"):
        assert nome in resposta.text


@pytest.mark.asyncio
async def test_filtro_por_uf_reduz_a_lista(admin):
    resposta = await admin.get("/portal/customers?uf=rs")

    assert "Beta Malharia" in resposta.text
    assert "Alfa Tecelagem" not in resposta.text


@pytest.mark.asyncio
async def test_cliente_de_outra_carteira_volta_para_a_lista(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await client.get(f"/portal/customers/{world.customer_b_id}")

    assert str(resposta.url).endswith("/portal/customers?m=nao-encontrado")
    assert "Registro não encontrado." in resposta.text


# --------------------------------------------------------------- cadastro


@pytest.mark.asyncio
async def test_cadastro_de_cliente_cria_a_localidade_padrao(world, admin):
    pagina = await admin.get("/portal/customers/novo")
    resposta = await admin.post(
        "/portal/customers/novo",
        data={
            "csrf_token": _token(pagina.text),
            "legal_name": "Delta Fiação Ltda.",
            "trade_name": "Delta",
            "state_code": "mg",
            "document_number": "44444444000144",
            "owner_user_id": str(world.representative_b_id),
        },
    )

    assert resposta.status_code == 200
    assert "Cliente cadastrado." in resposta.text
    assert "Principal" in resposta.text

    async with world.app.state.session_factory() as session:
        cliente = await session.scalar(
            select(Customer).where(Customer.legal_name == "Delta Fiação Ltda.")
        )
        local = await session.scalar(
            select(CustomerLocation).where(CustomerLocation.customer_id == cliente.id)
        )

    assert cliente.state_code == "MG"
    assert cliente.owner_user_id == world.representative_b_id
    assert (local.label, local.state_code, local.is_default) == ("Principal", "MG", True)


@pytest.mark.asyncio
async def test_uf_invalida_mostra_mensagem_em_portugues(admin):
    pagina = await admin.get("/portal/customers/novo")
    resposta = await admin.post(
        "/portal/customers/novo",
        data={"csrf_token": _token(pagina.text), "legal_name": "Zeta", "state_code": "XX"},
    )

    assert "UF inválida" in resposta.text
    assert "is not a Brazilian state code" not in resposta.text


@pytest.mark.asyncio
async def test_acentuacao_sobrevive_ao_formulario(world, admin):
    pagina = await admin.get("/portal/customers/novo")
    await admin.post(
        "/portal/customers/novo",
        data={
            "csrf_token": _token(pagina.text),
            "legal_name": "Tecelagem Conceição & Assunção Ltda.",
            "state_code": "SP",
        },
    )

    async with world.app.state.session_factory() as session:
        cliente = await session.scalar(
            select(Customer).where(Customer.trade_name.is_(None), Customer.state_code == "SP")
        )
        nomes = list(await session.scalars(select(Customer.legal_name)))

    assert "Tecelagem Conceição & Assunção Ltda." in nomes
    assert cliente is not None


@pytest.mark.asyncio
async def test_contato_e_criado_com_telefone_normalizado(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/contacts",
        data={
            "csrf_token": _token(pagina.text),
            "name": "Vitória Exemplo",
            "whatsapp_e164": "+55 (11) 99999-9999",
            "is_primary": "1",
        },
    )

    assert "Contato adicionado." in resposta.text
    assert "+5511999999999" in resposta.text

    async with world.app.state.session_factory() as session:
        contato = await session.scalar(select(CustomerContact))
    assert contato.is_primary is True


@pytest.mark.asyncio
async def test_telefone_invalido_mostra_mensagem_amigavel(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/contacts",
        data={"csrf_token": _token(pagina.text), "name": "Sem DDI", "whatsapp_e164": "11999"},
    )

    assert "Telefone inválido" in resposta.text


@pytest.mark.asyncio
async def test_localidade_padrao_nao_pode_ser_desativada(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    criada = await admin.post(
        f"/portal/customers/{world.customer_a_id}/locations",
        data={"csrf_token": _token(pagina.text), "label": "Matriz", "state_code": "SP"},
    )
    assert "Localidade adicionada." in criada.text

    async with world.app.state.session_factory() as session:
        local = await session.scalar(select(CustomerLocation))

    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/locations/{local.id}",
        data={"csrf_token": _token(criada.text), "acao": "desativar"},
    )

    assert "Promova outra localidade a padrão" in resposta.text


@pytest.mark.asyncio
async def test_transferencia_de_titular_pelo_portal(world, admin):
    pagina = await admin.get(f"/portal/customers/{world.customer_a_id}")
    resposta = await admin.post(
        f"/portal/customers/{world.customer_a_id}/owner",
        data={
            "csrf_token": _token(pagina.text),
            "owner_user_id": str(world.representative_b_id),
            "reason": "férias",
        },
    )

    assert "Titular atualizado." in resposta.text
    assert "Vendedor B" in resposta.text


@pytest.mark.asyncio
async def test_representante_nao_transfere_titular(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        pagina = await client.get(f"/portal/customers/{world.customer_a_id}")
        resposta = await client.post(
            f"/portal/customers/{world.customer_a_id}/owner",
            data={
                "csrf_token": _token(pagina.text),
                "owner_user_id": str(world.representative_b_id),
            },
        )

    assert "Seu papel não permite" in resposta.text

    async with world.app.state.session_factory() as session:
        cliente = await session.scalar(select(Customer).where(Customer.id == world.customer_a_id))
    assert cliente.owner_user_id == world.representative_a_id


# --------------------------------------------------------- representantes


@pytest.mark.asyncio
async def test_admin_cria_representante_pelo_portal(world, admin):
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Nova Vendedora",
            "email": "nova@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
        },
    )

    assert "Usuário criado." in resposta.text
    assert "nova@teste.com.br" in resposta.text

    async with world.app.state.session_factory() as session:
        criada = await session.scalar(select(User).where(User.email == "nova@teste.com.br"))
    assert criada.role.value == "REPRESENTATIVE"


@pytest.mark.asyncio
async def test_admin_cria_representante_com_whatsapp_livre(world, admin):
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Vendedora Com Zap",
            "email": "comzap@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "+551188887777",
        },
    )

    assert resposta.status_code == 200
    assert "Usuário criado." in resposta.text

    async with world.app.state.session_factory() as session:
        criada = await session.scalar(select(User).where(User.email == "comzap@teste.com.br"))
    # Canonizado na borda: o nono dígito entra no cadastro, não na consulta.
    assert criada.whatsapp_e164 == "+5511988887777"


@pytest.mark.asyncio
async def test_whatsapp_de_contato_de_cliente_nao_vira_500(world, admin):
    """A recusa é correta; o 500 era só a ausência de tradução.

    `_codigo_do_erro` relança o que não conhece, e `WhatsappAlreadyUsed` não
    estava na tabela — uma regra de negócio funcionando virava erro de servidor.
    """
    ocupado = "+5511975714368"
    async with world.app.state.session_factory() as session:
        session.add(
            CustomerContact(
                id=uuid4(),
                tenant_id=world.tenant_id,
                customer_id=world.customer_a_id,
                name="Compras Alfa",
                whatsapp_e164=ocupado,
                is_primary=True,
            )
        )
        await session.commit()

    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Colide Com Contato",
            "email": "colide@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": ocupado,
        },
    )

    assert resposta.status_code == 200
    assert "já está em uso" in resposta.text
    # Nada de tripa interna na tela.
    assert "Traceback" not in resposta.text
    assert "WhatsappAlreadyUsed" not in resposta.text

    async with world.app.state.session_factory() as session:
        # Nenhum registro parcial: o usuário não existe, e o contato segue dono
        # do número.
        assert await session.scalar(select(User).where(User.email == "colide@teste.com.br")) is None
        contato = await session.scalar(
            select(CustomerContact).where(CustomerContact.whatsapp_e164 == ocupado)
        )
        assert contato is not None


@pytest.mark.asyncio
async def test_whatsapp_de_outro_usuario_do_portal_tambem_e_recusado(world, admin):
    """Mesma exceção, outra origem — a colisão entre dois usuários do portal."""
    pagina = await admin.get("/portal/users")
    await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Primeiro Dono",
            "email": "primeiro@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "+5511966665555",
        },
    )

    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Segundo Dono",
            "email": "segundo@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "+5511966665555",
        },
    )

    assert resposta.status_code == 200
    assert "já está em uso" in resposta.text

    async with world.app.state.session_factory() as session:
        assert (
            await session.scalar(select(User).where(User.email == "segundo@teste.com.br"))
        ) is None


@pytest.mark.asyncio
async def test_email_duplicado_continua_com_a_mensagem_de_sempre(world, admin):
    """Regressão da tabela: acrescentar um código não pode mover os outros."""
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Repetido",
            "email": ADMIN_EMAIL,
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
        },
    )

    assert resposta.status_code == 200
    assert "Já existe um usuário com esse e-mail." in resposta.text


@pytest.mark.asyncio
async def test_telefone_invalido_continua_distinto_de_telefone_em_uso(admin):
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Telefone Torto",
            "email": "torto@teste.com.br",
            "password": "OutraSenhaBoa2026",
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "1199",
        },
    )

    assert resposta.status_code == 200
    assert "Telefone inválido" in resposta.text
    assert "já está em uso" not in resposta.text


@pytest.mark.asyncio
async def test_senha_fraca_explica_a_politica(admin):
    pagina = await admin.get("/portal/users")
    resposta = await admin.post(
        "/portal/users",
        data={
            "csrf_token": _token(pagina.text),
            "full_name": "Fraca",
            "email": "fraca@teste.com.br",
            "password": "curta1",
            "role": "REPRESENTATIVE",
        },
    )

    assert "Senha recusada" in resposta.text


@pytest.mark.asyncio
async def test_admin_nao_desativa_a_propria_conta(world, admin):
    pagina = await admin.get("/portal/users")

    # A tela não oferece o botão para a própria conta.
    assert f'action="/portal/users/{world.admin_id}"' not in pagina.text

    # E a rota recusa mesmo se o POST for forjado à mão.
    resposta = await admin.post(
        f"/portal/users/{world.admin_id}",
        data={"csrf_token": _token(pagina.text), "acao": "desativar"},
    )
    assert "não pode desativar a própria conta" in resposta.text


@pytest.mark.asyncio
async def test_representante_nao_alcanca_a_tela_de_usuarios(world):
    async with _browser(world) as client:
        await _entrar(client, REPRESENTATIVE_A_EMAIL)
        resposta = await client.get("/portal/users")

    assert str(resposta.url).endswith("/portal/customers?m=sem-permissao")
    assert "Seu papel não permite" in resposta.text


@pytest.mark.asyncio
async def test_folha_de_estilo_e_servida(world):
    async with _browser(world) as client:
        resposta = await client.get("/portal/static/portal.css")

    assert resposta.status_code == 200
    assert "text/css" in resposta.headers["content-type"]
