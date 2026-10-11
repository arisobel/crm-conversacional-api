"""Decisão de atendimento por carteira na linha do representante (portfolio-v1).

A linha da Vendedora A só aciona o robô para contato de cliente cuja titular é
ela. Cada teste é um caso da tabela do plano (A–K, N); o Gateway trata tudo que
não for `200` com `ALLOW` como negação, então os de contrato também importam.
"""

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import ADMIN_EMAIL, build_portal_world, login
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import AuditLog, User, UserRole
from crm_api.models.whatsapp_connection import (
    RepresentativeWhatsappConnection,
    WhatsappConnectionStatus,
)

CAMINHO = "/internal/whatsapp/authorization-decision"
LINHA_A = "6f2d8c1e-0000-4000-8000-00000000000a"
LINHA_B = "6f2d8c1e-0000-4000-8000-00000000000b"
LINHA_FALHA = "6f2d8c1e-0000-4000-8000-0000000000ff"

CLIENTE_DE_A = "+5511988887777"
CLIENTE_DE_B = "+5511977776666"
CLIENTE_SEM_TITULAR = "+5511966665555"
CLIENTE_INATIVO = "+5511955554444"
CONTATO_INATIVO = "+5511944443333"
COMPARTILHADO = "+5511933332222"
TELEFONE_ADMIN = "+5511922221111"
DESCONHECIDO = "+5541900000000"


def _conexao(world, user_id, referencia, status=WhatsappConnectionStatus.CONNECTED):
    return RepresentativeWhatsappConnection(
        id=uuid4(),
        tenant_id=world.tenant_id,
        representative_user_id=user_id,
        status=status,
        idempotency_key=uuid4().hex,
        gateway_line_reference=referencia,
        display_phone_number="+5511900000000",
        created_by_user_id=world.admin_id,
    )


def _contato(world, customer_id, telefone, *, active=True):
    return CustomerContact(
        id=uuid4(),
        tenant_id=world.tenant_id,
        customer_id=customer_id,
        name="Compras",
        whatsapp_e164=telefone,
        active=active,
    )


@pytest_asyncio.fixture
async def world():
    mundo = await build_portal_world()
    async with mundo.app.state.session_factory() as session:
        inativo = Customer(
            id=uuid4(),
            tenant_id=mundo.tenant_id,
            legal_name="Delta Fios Ltda.",
            state_code="SP",
            owner_user_id=mundo.representative_a_id,
            active=False,
        )
        session.add(inativo)
        await session.flush()
        session.add_all(
            [
                _conexao(mundo, mundo.representative_a_id, LINHA_A),
                _conexao(mundo, mundo.representative_b_id, LINHA_B),
                _conexao(
                    mundo,
                    mundo.representative_b_id,
                    LINHA_FALHA,
                    status=WhatsappConnectionStatus.FAILED,
                ),
                _contato(mundo, mundo.customer_a_id, CLIENTE_DE_A),
                _contato(mundo, mundo.customer_a_id, CONTATO_INATIVO, active=False),
                _contato(mundo, mundo.customer_a_id, COMPARTILHADO),
                _contato(mundo, mundo.customer_b_id, CLIENTE_DE_B),
                _contato(mundo, mundo.customer_unassigned_id, CLIENTE_SEM_TITULAR),
                _contato(mundo, inativo.id, CLIENTE_INATIVO),
            ]
        )
        # O cadastro recusa telefone de usuário igual ao de contato; aqui é o
        # dado anterior a essa regra, gravado direto.
        (await session.get(User, mundo.representative_b_id)).whatsapp_e164 = COMPARTILHADO
        (await session.get(User, mundo.admin_id)).whatsapp_e164 = TELEFONE_ADMIN
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


def _corpo(telefone: str, linha: str = LINHA_A, **extra) -> bytes:
    return json.dumps(
        {
            "gateway_line_reference": linha,
            "phone_e164": telefone,
            "application_slug": "crm_textil",
            "flow_slug": "consulta_cliente",
            "message_id": "wamid.TESTE",
            **extra,
        }
    ).encode("utf-8")


async def _decidir(world, telefone: str, linha: str = LINHA_A, *, secret=b"test-secret"):
    corpo = _corpo(telefone, linha)
    async with _cliente(world) as client:
        return await client.post(CAMINHO, content=corpo, headers=_assinado(corpo, secret=secret))


async def _negado(world, telefone: str, linha: str = LINHA_A) -> str:
    resposta = await _decidir(world, telefone, linha)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["decision"] == "DENY"
    # Em DENY, nenhum dado de cliente atravessa para o Gateway.
    assert "customer_public_ref" not in corpo
    assert "contact_public_ref" not in corpo
    assert corpo["policy_version"] == "portfolio-v1"
    return corpo["reason"]


# ------------------------------------------------------------------ casos


@pytest.mark.asyncio
async def test_a_cliente_da_dona_da_linha_e_atendido(world):
    resposta = await _decidir(world, CLIENTE_DE_A)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["decision"] == "ALLOW"
    assert corpo["reason"] == "AUTHORIZED"
    assert corpo["customer_public_ref"] == str(world.customer_a_id)
    assert len(corpo["contact_public_ref"]) == 24


@pytest.mark.asyncio
async def test_a_grafia_sem_nono_digito_resolve_para_o_mesmo_cliente(world):
    resposta = await _decidir(world, "+551188887777")

    assert resposta.json()["decision"] == "ALLOW"


@pytest.mark.asyncio
async def test_b_cliente_de_outro_representante_e_negado(world):
    assert await _negado(world, CLIENTE_DE_B) == "OWNER_MISMATCH"


@pytest.mark.asyncio
async def test_b_a_mesma_regra_vale_na_linha_do_outro_representante(world):
    assert (await _decidir(world, CLIENTE_DE_B, LINHA_B)).json()["decision"] == "ALLOW"
    assert await _negado(world, CLIENTE_DE_A, LINHA_B) == "OWNER_MISMATCH"


@pytest.mark.asyncio
async def test_c_cliente_sem_titular_e_negado(world):
    assert await _negado(world, CLIENTE_SEM_TITULAR) == "CUSTOMER_WITHOUT_OWNER"


@pytest.mark.asyncio
async def test_d_cliente_inativo_e_negado(world):
    assert await _negado(world, CLIENTE_INATIVO) == "CUSTOMER_INACTIVE"


@pytest.mark.asyncio
async def test_e_telefone_desconhecido_e_negado(world):
    assert await _negado(world, DESCONHECIDO) == "CONTACT_NOT_FOUND"


@pytest.mark.asyncio
async def test_e_telefone_malformado_e_desconhecido_e_nao_erro_de_contrato(world):
    assert await _negado(world, "não é telefone") == "CONTACT_NOT_FOUND"


@pytest.mark.asyncio
async def test_f_contato_inativo_de_cliente_da_dona_e_negado(world):
    assert await _negado(world, CONTATO_INATIVO) == "CONTACT_NOT_FOUND"


@pytest.mark.asyncio
async def test_g_dona_da_linha_inativa_nega_ate_cliente_dela(world):
    async with world.app.state.session_factory() as session:
        (await session.get(User, world.representative_a_id)).active = False
        await session.commit()

    assert await _negado(world, CLIENTE_DE_A) == "LINE_OWNER_INACTIVE"


@pytest.mark.asyncio
async def test_g_dona_da_linha_que_deixou_de_ser_representante_nega(world):
    async with world.app.state.session_factory() as session:
        (await session.get(User, world.representative_a_id)).role = UserRole.MANAGER
        await session.commit()

    assert await _negado(world, CLIENTE_DE_A) == "LINE_OWNER_INACTIVE"


@pytest.mark.asyncio
async def test_h_telefone_de_contato_e_de_usuario_ao_mesmo_tempo_e_ambiguo(world):
    assert await _negado(world, COMPARTILHADO) == "AMBIGUOUS_PHONE"


@pytest.mark.asyncio
async def test_i_telefone_de_admin_e_usuario_interno(world):
    assert await _negado(world, TELEFONE_ADMIN) == "INTERNAL_USER"


@pytest.mark.asyncio
async def test_j_linha_sem_referencia_no_crm_e_negada(world):
    assert await _negado(world, CLIENTE_DE_A, "referencia-que-nao-existe") == "LINE_UNKNOWN"


@pytest.mark.asyncio
async def test_j_conexao_que_nao_esta_conectada_nao_vale(world):
    assert await _negado(world, CLIENTE_DE_B, LINHA_FALHA) == "LINE_UNKNOWN"


@pytest.mark.asyncio
async def test_j_mesma_referencia_em_duas_conexoes_e_negada(world):
    async with world.app.state.session_factory() as session:
        session.add(_conexao(world, world.inactive_user_id, LINHA_A))
        await session.commit()

    assert await _negado(world, CLIENTE_DE_A) == "LINE_UNKNOWN"


@pytest.mark.asyncio
async def test_k_transferencia_de_titular_vale_na_mensagem_seguinte(world):
    assert (await _decidir(world, CLIENTE_DE_A)).json()["decision"] == "ALLOW"

    async with _cliente(world) as admin:
        await login(admin, email=ADMIN_EMAIL)
        transferencia = await admin.put(
            f"/admin/customers/{world.customer_a_id}/owner",
            json={"owner_user_id": str(world.representative_b_id), "reason": "transferência"},
        )
    assert transferencia.status_code == 200

    assert await _negado(world, CLIENTE_DE_A) == "OWNER_MISMATCH"
    assert (await _decidir(world, CLIENTE_DE_A, LINHA_B)).json()["decision"] == "ALLOW"


# ------------------------------------------------------------------ auditoria


@pytest.mark.asyncio
async def test_negacao_fica_na_auditoria_sem_o_telefone_inteiro(world):
    await _negado(world, CLIENTE_DE_B)

    async with world.app.state.session_factory() as session:
        registro = await session.scalar(
            select(AuditLog).where(AuditLog.action == "WHATSAPP_AUTHORIZATION_DENIED")
        )
    assert registro is not None
    assert registro.tenant_id == world.tenant_id
    assert registro.request_id == "wamid.TESTE"
    assert registro.after["reason"] == "OWNER_MISMATCH"
    assert registro.after["phone_suffix"] == "***6666"
    assert CLIENTE_DE_B not in json.dumps(registro.after)


@pytest.mark.asyncio
async def test_atendimento_autorizado_nao_grava_auditoria(world):
    await _decidir(world, CLIENTE_DE_A)

    async with world.app.state.session_factory() as session:
        registros = (await session.scalars(select(AuditLog))).all()
    assert registros == []


# ------------------------------------------------------------------ contrato


@pytest.mark.asyncio
async def test_assinatura_invalida_e_401(world):
    resposta = await _decidir(world, CLIENTE_DE_A, secret=b"outro-segredo")

    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_campo_desconhecido_e_recusado(world):
    corpo = _corpo(CLIENTE_DE_A, extra_field="x")
    async with _cliente(world) as client:
        resposta = await client.post(CAMINHO, content=corpo, headers=_assinado(corpo))

    assert resposta.status_code == 422
