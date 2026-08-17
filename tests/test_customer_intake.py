"""Pré-cadastro de cliente aberto pelo representante (W7).

O que está sob teste não é só o caminho felizardo. São três invariantes que a
escrita pelo WhatsApp não pode violar, e cada uma tem um teste que falha se
alguém as afrouxar:

1. **Abrir pré-cadastro não cria cliente nem autoriza telefone.** Enquanto
   ninguém aceitar no portal, o roster não muda — logo o Gateway não passa a
   atender o número ditado na mensagem.
2. **O titular é quem abriu, não quem aceitou.** Um `ADMIN` resolvendo a fila no
   escritório não se torna dono da conta.
3. **A reentrega do webhook não duplica.** A chave é o `wamid`.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.customer_intake import CustomerIntake, IntakeStatus
from crm_api.models.user import User, UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.customer_intakes import CustomerIntakeRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository, PortfolioScope
from crm_api.repositories.users import UserRepository
from crm_api.services.customer_admin import CustomerAdminService
from crm_api.services.customer_intake import (
    CustomerIntakeService,
    IntakeAlreadyResolved,
    IntakeNotFound,
)

BASE = "/internal/representative/by-whatsapp"
TELEFONE_A = "+5511987654321"  # representante A
TELEFONE_B = "+5511955553333"  # representante B
TELEFONE_CLIENTE = "+5511988887777"
NOVO_CLIENTE = "+5511977776666"


@pytest_asyncio.fixture
async def world():
    mundo = await build_portal_world()
    async with mundo.app.state.session_factory() as session:
        for user_id, telefone in (
            (mundo.representative_a_id, TELEFONE_A),
            (mundo.representative_b_id, TELEFONE_B),
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
        await session.commit()

    yield mundo
    await mundo.app.state.engine.dispose()


def _headers(path: str, body: bytes, *, secret: bytes = b"test-secret") -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join([timestamp.encode(), b"POST", path.encode(), body])
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(secret, canonical, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


async def _abrir(world, telefone: str, corpo: dict, *, secret: bytes = b"test-secret"):
    path = f"{BASE}/{telefone}/customer-intakes"
    body = json.dumps(corpo).encode()
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://testserver"
    ) as client:
        return await client.post(path, content=body, headers=_headers(path, body, secret=secret))


def _corpo(**overrides) -> dict:
    base = {
        "idempotency_key": "wamid.TESTE00000000000001",
        "legal_name": "Malhas Silva Ltda",
        "state_code": "SP",
        "whatsapp_e164": NOVO_CLIENTE,
        "preferred_products_text": "gosta de 75/36 urdume",
    }
    base.update(overrides)
    return base


def _service(session) -> CustomerIntakeService:
    admin = CustomerAdminRepository(session)
    audit = AuditRepository(session)
    return CustomerIntakeService(
        intakes=CustomerIntakeRepository(session),
        admin=admin,
        users=UserRepository(session),
        customers=CustomerAdminService(
            portfolio=CustomerPortfolioRepository(session), admin=admin, audit=audit
        ),
        audit=audit,
    )


# ------------------------------------------------------------------- abertura


@pytest.mark.asyncio
async def test_representante_abre_pre_cadastro(world):
    resposta = await _abrir(world, TELEFONE_A, _corpo())

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["status"] == "PENDING"
    assert corpo["legal_name"] == "Malhas Silva Ltda"
    assert corpo["state_code"] == "SP"
    assert corpo["has_whatsapp"] is True
    assert corpo["preferred_products_text"] == "gosta de 75/36 urdume"
    assert corpo["created"] is True


@pytest.mark.asyncio
async def test_abrir_nao_cria_cliente_nem_autoriza_telefone(world):
    """A invariante central da W7.

    Se a mensagem gravasse o contato direto, uma frase no WhatsApp autorizaria um
    telefone qualquer a conversar com o CRM.
    """
    async with world.app.state.session_factory() as session:
        clientes_antes = await session.scalar(select(func.count()).select_from(Customer))

    await _abrir(world, TELEFONE_A, _corpo())

    async with world.app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Customer)) == clientes_antes
        contato = await session.scalar(
            select(CustomerContact).where(CustomerContact.whatsapp_e164 == NOVO_CLIENTE)
        )
        assert contato is None


@pytest.mark.asyncio
async def test_o_telefone_do_pre_cadastro_nao_entra_no_roster(world):
    """Segunda metade da mesma invariante, vista pelo consumidor.

    O roster é o que o Gateway espelha; é ele que decide quem o canal atende.
    """
    await _abrir(world, TELEFONE_A, _corpo())

    path = "/internal/authorized-contacts"
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join([timestamp.encode(), b"GET", path.encode(), b""])
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://testserver"
    ) as client:
        roster = await client.get(
            path,
            headers={
                "X-Tenant-Slug": "test-tenant",
                "X-Timestamp": timestamp,
                "X-Signature": hmac.new(
                    b"test-secret", canonical, hashlib.sha256
                ).hexdigest(),
            },
        )

    assert roster.status_code == 200
    assert NOVO_CLIENTE not in roster.json()["contacts"]


@pytest.mark.asyncio
async def test_reentrega_do_webhook_nao_duplica(world):
    primeira = await _abrir(world, TELEFONE_A, _corpo())
    segunda = await _abrir(world, TELEFONE_A, _corpo())

    assert primeira.status_code == segunda.status_code == 201
    assert primeira.json()["intake_id"] == segunda.json()["intake_id"]
    assert primeira.json()["created"] is True
    assert segunda.json()["created"] is False

    async with world.app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(CustomerIntake)) == 1


@pytest.mark.asyncio
async def test_mensagem_diferente_abre_outro_pre_cadastro(world):
    await _abrir(world, TELEFONE_A, _corpo())
    outra = await _abrir(
        world,
        TELEFONE_A,
        _corpo(
            idempotency_key="wamid.TESTE00000000000002",
            legal_name="Tecelagem Aurora",
            whatsapp_e164=None,
        ),
    )

    assert outra.status_code == 201
    async with world.app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(CustomerIntake)) == 2


@pytest.mark.asyncio
async def test_pre_cadastro_sem_telefone_e_sem_preferencia(world):
    resposta = await _abrir(
        world, TELEFONE_A, _corpo(whatsapp_e164=None, preferred_products_text=None)
    )

    assert resposta.status_code == 201
    assert resposta.json()["has_whatsapp"] is False
    assert resposta.json()["preferred_products_text"] is None


@pytest.mark.asyncio
async def test_telefone_sem_nono_digito_e_canonizado(world):
    await _abrir(world, TELEFONE_A, _corpo(whatsapp_e164="+551177776666"))

    async with world.app.state.session_factory() as session:
        intake = await session.scalar(select(CustomerIntake))
        assert intake.whatsapp_e164 == NOVO_CLIENTE


# --------------------------------------------------------------------- portas


@pytest.mark.asyncio
async def test_contato_de_cliente_nao_abre_pre_cadastro(world):
    """Segunda tranca: o manifesto de cliente não anuncia esta ação."""
    resposta = await _abrir(world, TELEFONE_CLIENTE, _corpo())
    assert resposta.status_code == 403


@pytest.mark.asyncio
async def test_assinatura_errada_nao_abre_a_porta(world):
    resposta = await _abrir(world, TELEFONE_A, _corpo(), secret=b"outra")
    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_uf_invalida_recusa(world):
    resposta = await _abrir(world, TELEFONE_A, _corpo(state_code="XX"))
    assert resposta.status_code == 422


@pytest.mark.asyncio
async def test_telefone_de_contato_existente_responde_409(world):
    resposta = await _abrir(world, TELEFONE_A, _corpo(whatsapp_e164=TELEFONE_CLIENTE))
    assert resposta.status_code == 409


@pytest.mark.asyncio
async def test_telefone_de_usuario_do_portal_responde_409(world):
    """A colisão que derrubou a produção: telefone que é usuário e contato.

    Recusar na abertura é mais barato que descobrir na aceitação — e muito mais
    barato que o `409` do manifesto depois, quando o número já parou de responder.
    """
    resposta = await _abrir(world, TELEFONE_A, _corpo(whatsapp_e164=TELEFONE_B))
    assert resposta.status_code == 409


@pytest.mark.asyncio
async def test_razao_social_em_branco_recusa(world):
    resposta = await _abrir(world, TELEFONE_A, _corpo(legal_name="   "))
    assert resposta.status_code == 422


# ------------------------------------------------------------------ aceitação


@pytest.mark.asyncio
async def test_aceitar_cria_cliente_na_carteira_de_quem_abriu(world):
    """A titularidade é de quem abriu, mesmo quando um `ADMIN` resolve a fila."""
    await _abrir(world, TELEFONE_A, _corpo())

    async with world.app.state.session_factory() as session:
        intake = await session.scalar(select(CustomerIntake))
        aceito = await _service(session).accept(
            world.tenant_id,
            intake.id,
            actor_user_id=world.admin_id,
            actor_role=UserRole.ADMIN,
        )
        await session.commit()

        assert aceito.status is IntakeStatus.ACCEPTED
        cliente = await session.get(Customer, aceito.customer_id)
        assert cliente.legal_name == "Malhas Silva Ltda"
        assert cliente.state_code == "SP"
        assert cliente.owner_user_id == world.representative_a_id

        contato = await session.scalar(
            select(CustomerContact).where(CustomerContact.customer_id == cliente.id)
        )
        assert contato.whatsapp_e164 == NOVO_CLIENTE
        assert contato.is_primary is True


@pytest.mark.asyncio
async def test_aceitar_pode_corrigir_os_dados_ditados(world):
    """O que foi ditado no WhatsApp é ponto de partida, não verdade cadastral."""
    await _abrir(world, TELEFONE_A, _corpo())

    async with world.app.state.session_factory() as session:
        intake = await session.scalar(select(CustomerIntake))
        aceito = await _service(session).accept(
            world.tenant_id,
            intake.id,
            actor_user_id=world.admin_id,
            actor_role=UserRole.ADMIN,
            legal_name="Malhas Silva Comércio Ltda",
            state_code="MG",
            document_number="12345678000199",
        )
        await session.commit()

        cliente = await session.get(Customer, aceito.customer_id)
        assert cliente.legal_name == "Malhas Silva Comércio Ltda"
        assert cliente.state_code == "MG"
        assert cliente.document_number == "12345678000199"


@pytest.mark.asyncio
async def test_pre_cadastro_sem_telefone_nao_cria_contato(world):
    await _abrir(world, TELEFONE_A, _corpo(whatsapp_e164=None))

    async with world.app.state.session_factory() as session:
        intake = await session.scalar(select(CustomerIntake))
        aceito = await _service(session).accept(
            world.tenant_id,
            intake.id,
            actor_user_id=world.admin_id,
            actor_role=UserRole.ADMIN,
        )
        await session.commit()

        contatos = await session.scalars(
            select(CustomerContact).where(CustomerContact.customer_id == aceito.customer_id)
        )
        assert list(contatos) == []


@pytest.mark.asyncio
async def test_aceitar_duas_vezes_recusa(world):
    await _abrir(world, TELEFONE_A, _corpo())

    async with world.app.state.session_factory() as session:
        intake = await session.scalar(select(CustomerIntake))
        servico = _service(session)
        await servico.accept(
            world.tenant_id,
            intake.id,
            actor_user_id=world.admin_id,
            actor_role=UserRole.ADMIN,
        )
        await session.commit()

        with pytest.raises(IntakeAlreadyResolved):
            await servico.accept(
                world.tenant_id,
                intake.id,
                actor_user_id=world.admin_id,
                actor_role=UserRole.ADMIN,
            )


@pytest.mark.asyncio
async def test_representante_nao_alcanca_pre_cadastro_de_outro(world):
    """Mesmo corpo de erro de um id inexistente, como no resto do portal."""
    await _abrir(world, TELEFONE_A, _corpo())

    async with world.app.state.session_factory() as session:
        intake = await session.scalar(select(CustomerIntake))
        with pytest.raises(IntakeNotFound):
            await _service(session).accept(
                world.tenant_id,
                intake.id,
                actor_user_id=world.representative_b_id,
                actor_role=UserRole.REPRESENTATIVE,
            )


@pytest.mark.asyncio
async def test_representante_aceita_o_proprio(world):
    """Não é privilégio novo: o R2 já permite que ele crie cliente pelo portal."""
    await _abrir(world, TELEFONE_A, _corpo())

    async with world.app.state.session_factory() as session:
        intake = await session.scalar(select(CustomerIntake))
        aceito = await _service(session).accept(
            world.tenant_id,
            intake.id,
            actor_user_id=world.representative_a_id,
            actor_role=UserRole.REPRESENTATIVE,
        )
        await session.commit()

        cliente = await session.get(Customer, aceito.customer_id)
        assert cliente.owner_user_id == world.representative_a_id


@pytest.mark.asyncio
async def test_telefone_ocupado_entre_abrir_e_aceitar_recusa(world):
    """Entre abrir e aceitar pode passar uma semana.

    Sem revalidar, a aceitação criaria a colisão que o manifesto recusa com
    `409` — e o número pararia de ser atendido sem ninguém saber por quê.
    """
    from crm_api.services.customer_intake import WhatsappAlreadyUsed

    await _abrir(world, TELEFONE_A, _corpo())

    async with world.app.state.session_factory() as session:
        session.add(
            CustomerContact(
                id=uuid4(),
                tenant_id=world.tenant_id,
                customer_id=world.customer_b_id,
                name="Alguém digitou primeiro",
                whatsapp_e164=NOVO_CLIENTE,
            )
        )
        await session.commit()

        intake = await session.scalar(select(CustomerIntake))
        with pytest.raises(WhatsappAlreadyUsed):
            await _service(session).accept(
                world.tenant_id,
                intake.id,
                actor_user_id=world.admin_id,
                actor_role=UserRole.ADMIN,
            )


# ------------------------------------------------------------------ rejeição


@pytest.mark.asyncio
async def test_rejeitar_exige_motivo_e_nao_cria_cliente(world):
    from crm_api.services.customer_intake import BlankField

    await _abrir(world, TELEFONE_A, _corpo())

    async with world.app.state.session_factory() as session:
        intake = await session.scalar(select(CustomerIntake))
        servico = _service(session)

        with pytest.raises(BlankField):
            await servico.reject(
                world.tenant_id,
                intake.id,
                actor_user_id=world.admin_id,
                actor_role=UserRole.ADMIN,
                reason="   ",
            )

        rejeitado = await servico.reject(
            world.tenant_id,
            intake.id,
            actor_user_id=world.admin_id,
            actor_role=UserRole.ADMIN,
            reason="cliente já existe com outra razão social",
        )
        await session.commit()

        assert rejeitado.status is IntakeStatus.REJECTED
        assert rejeitado.customer_id is None
        assert rejeitado.rejected_reason == "cliente já existe com outra razão social"


# ---------------------------------------------------------------------- fila


@pytest.mark.asyncio
async def test_a_fila_do_representante_mostra_apenas_os_dele(world):
    await _abrir(world, TELEFONE_A, _corpo())
    await _abrir(
        world,
        TELEFONE_B,
        _corpo(
            idempotency_key="wamid.TESTE00000000000009",
            legal_name="Do outro representante",
            whatsapp_e164=None,
        ),
    )

    async with world.app.state.session_factory() as session:
        servico = _service(session)

        dele, total_dele = await servico.queue(
            PortfolioScope(tenant_id=world.tenant_id, owner_user_id=world.representative_a_id),
            actor_role=UserRole.REPRESENTATIVE,
        )
        assert total_dele == 1
        assert dele[0][0].legal_name == "Malhas Silva Ltda"

        todos, total = await servico.queue(
            PortfolioScope(tenant_id=world.tenant_id, owner_user_id=None),
            actor_role=UserRole.ADMIN,
        )
        assert total == 2
        assert len(todos) == 2
