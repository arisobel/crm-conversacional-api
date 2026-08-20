"""A fila do portal resolve, sem duplicar, os pré-cadastros do WhatsApp."""

import re
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import (
    ADMIN_EMAIL,
    PASSWORD,
    REPRESENTATIVE_A_EMAIL,
    REPRESENTATIVE_B_EMAIL,
    build_portal_world,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.customer_intake import CustomerIntake, IntakeStatus

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    yield built
    await built.app.state.engine.dispose()


@asynccontextmanager
async def _browser(world):
    async with AsyncClient(
        transport=ASGITransport(app=world.app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client


def _token(html: str) -> str:
    found = _CSRF.search(html)
    assert found, "página não trouxe campo csrf_token"
    return found.group(1)


async def _entrar(client, email: str):
    page = await client.get("/portal/login")
    return await client.post(
        "/portal/login",
        data={"email": email, "password": PASSWORD, "csrf_token": _token(page.text)},
    )


async def _intake(world, *, author_id, name: str, phone: str | None = None) -> CustomerIntake:
    intake = CustomerIntake(
        id=uuid4(),
        tenant_id=world.tenant_id,
        created_by_user_id=author_id,
        idempotency_key=f"wamid.{uuid4()}",
        legal_name=name,
        state_code="SP",
        whatsapp_e164=phone,
    )
    async with world.app.state.session_factory() as session:
        session.add(intake)
        await session.commit()
    return intake


@pytest.mark.asyncio
async def test_fila_respeita_escopo_do_representante_e_admin_ve_toda_a_fila(world):
    await _intake(world, author_id=world.representative_a_id, name="Malhas Alfa")
    await _intake(world, author_id=world.representative_b_id, name="Fios Beta")

    async with _browser(world) as representative:
        await _entrar(representative, REPRESENTATIVE_A_EMAIL)
        page = await representative.get("/portal/intakes")

    assert "Malhas Alfa" in page.text
    assert "Fios Beta" not in page.text

    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        page = await admin.get("/portal/intakes")

    assert "Malhas Alfa" in page.text
    assert "Fios Beta" in page.text


@pytest.mark.asyncio
async def test_admin_aceita_pre_cadastro_cria_cliente_contato_e_preserva_titular(world):
    intake = await _intake(
        world,
        author_id=world.representative_a_id,
        name="Tecelagem Horizonte Ltda.",
        phone="+5511999887766",
    )

    async with _browser(world) as admin:
        await _entrar(admin, ADMIN_EMAIL)
        page = await admin.get("/portal/intakes")
        response = await admin.post(
            f"/portal/intakes/{intake.id}/accept",
            data={
                "legal_name": "Tecelagem Horizonte Ltda.",
                "state_code": "SP",
                "trade_name": "Horizonte",
                "document_number": "12345678000190",
                "contact_name": "Ana da Horizonte",
                "csrf_token": _token(page.text),
            },
        )

    assert "Pré-cadastro aceito e cliente criado." in response.text
    async with world.app.state.session_factory() as session:
        persisted = await session.get(CustomerIntake, intake.id)
        customer = await session.get(Customer, persisted.customer_id)
        contact = await session.scalar(
            select(CustomerContact).where(CustomerContact.customer_id == customer.id)
        )

    assert persisted.status is IntakeStatus.ACCEPTED
    assert customer.owner_user_id == world.representative_a_id
    assert customer.trade_name == "Horizonte"
    assert contact.whatsapp_e164 == "+5511999887766"
    assert contact.name == "Ana da Horizonte"


@pytest.mark.asyncio
async def test_representante_nao_resolve_pre_cadastro_de_outro_representante(world):
    intake = await _intake(world, author_id=world.representative_a_id, name="Malhas Protegidas")

    async with _browser(world) as representative:
        await _entrar(representative, REPRESENTATIVE_B_EMAIL)
        page = await representative.get("/portal/intakes")
        response = await representative.post(
            f"/portal/intakes/{intake.id}/reject",
            data={"reason": "tentativa indevida", "csrf_token": _token(page.text)},
        )

    assert "Registro não encontrado." in response.text
    async with world.app.state.session_factory() as session:
        persisted = await session.get(CustomerIntake, intake.id)
    assert persisted.status is IntakeStatus.PENDING


@pytest.mark.asyncio
async def test_rejeicao_exige_motivo_e_grava_o_estado_final(world):
    intake = await _intake(world, author_id=world.representative_a_id, name="Cadastro Incompleto")

    async with _browser(world) as representative:
        await _entrar(representative, REPRESENTATIVE_A_EMAIL)
        page = await representative.get("/portal/intakes")
        response = await representative.post(
            f"/portal/intakes/{intake.id}/reject",
            data={"reason": "   ", "csrf_token": _token(page.text)},
        )
        assert "Preencha o campo obrigatório." in response.text

        page = await representative.get("/portal/intakes")
        response = await representative.post(
            f"/portal/intakes/{intake.id}/reject",
            data={"reason": "Documento precisa ser confirmado", "csrf_token": _token(page.text)},
        )

    assert "Pré-cadastro rejeitado." in response.text
    async with world.app.state.session_factory() as session:
        persisted = await session.get(CustomerIntake, intake.id)
    assert persisted.status is IntakeStatus.REJECTED
    assert persisted.rejected_reason == "Documento precisa ser confirmado"
