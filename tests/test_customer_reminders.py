import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import build_portal_world
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.customer_contact import CustomerContact
from crm_api.models.reminder import ReminderOrigin, ReminderStatus, RepresentativeReminder
from crm_api.models.user import User
from crm_api.models.whatsapp_connection import (
    RepresentativeWhatsappConnection,
    WhatsappConnectionStatus,
)

PATH = "/internal/whatsapp/customer-reminders"
LINE = "coexistence-line-a"
PHONE = "+5511987654321"
REP_PHONE = "+5511912345678"


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    async with built.app.state.session_factory() as session:
        representative = await session.get(User, built.representative_a_id)
        representative.whatsapp_e164 = REP_PHONE
        session.add_all(
            [
                CustomerContact(
                    id=uuid4(),
                    tenant_id=built.tenant_id,
                    customer_id=built.customer_a_id,
                    name="Compras Alfa",
                    whatsapp_e164=PHONE,
                    active=True,
                ),
                RepresentativeWhatsappConnection(
                    id=uuid4(),
                    tenant_id=built.tenant_id,
                    representative_user_id=built.representative_a_id,
                    status=WhatsappConnectionStatus.CONNECTED,
                    idempotency_key=uuid4().hex,
                    gateway_line_reference=LINE,
                    display_phone_number="+5511900000000",
                    created_by_user_id=built.admin_id,
                ),
            ]
        )
        await session.commit()
    yield built
    await built.app.state.engine.dispose()


def signed(body: bytes) -> dict[str, str]:
    return signed_for(PATH, body)


def signed_for(path: str, body: bytes) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    canonical = b".".join([timestamp.encode(), b"POST", path.encode(), body])
    return {
        "X-Tenant-Slug": "test-tenant",
        "X-Timestamp": timestamp,
        "X-Signature": hmac.new(b"test-secret", canonical, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


async def create(world, *, wamid="wamid.REMINDER.1", line=LINE, due_at=None):
    body = json.dumps(
        {
            "gateway_line_reference": line,
            "customer_phone_e164": PHONE,
            "source_wamid": wamid,
            "kind": "CALL",
            "due_at": (due_at or datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "note": "me liga amanhã às 10",
        }
    ).encode()
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as client:
        return await client.post(PATH, content=body, headers=signed(body))


@pytest.mark.asyncio
async def test_cliente_cria_compromisso_confirmado_para_o_titular(world):
    response = await create(world)

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is True
    assert payload["status"] == ReminderStatus.CONFIRMED
    assert payload["representative_phone_e164"] == REP_PHONE
    assert payload["customer_name"] == "Alfa Tecelagem Ltda."
    async with world.app.state.session_factory() as session:
        reminder = await session.scalar(select(RepresentativeReminder))
        assert reminder.representative_user_id == world.representative_a_id
        assert reminder.customer_id == world.customer_a_id


@pytest.mark.asyncio
async def test_reenvio_do_mesmo_wamid_nao_duplica(world):
    first = await create(world)
    second = await create(world)

    assert first.status_code == second.status_code == 200
    assert first.json()["reminder_id"] == second.json()["reminder_id"]
    assert second.json()["created"] is False


@pytest.mark.asyncio
async def test_nao_cria_dois_compromissos_na_mesma_hora_do_representante(world):
    due_at = (datetime.now(UTC) + timedelta(days=2)).replace(minute=10, second=0, microsecond=0)
    first = await create(world, wamid="wamid.SLOT.1", due_at=due_at)
    conflict = await create(
        world,
        wamid="wamid.SLOT.2",
        due_at=due_at.replace(minute=50),
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "representative reminder slot conflict"


@pytest.mark.asyncio
async def test_linha_que_nao_pertence_ao_titular_e_negada(world):
    response = await create(world, line="wrong-line")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_horario_passado_e_rejeitado(world):
    response = await create(world, due_at=datetime.now(UTC) - timedelta(minutes=1))

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_aviso_e_reservado_uma_hora_antes_e_confirmado_sem_duplicar(world):
    due_at = datetime.now(UTC) + timedelta(minutes=50)
    created = await create(world, wamid="wamid.NOTIFY.1", due_at=due_at)
    assert created.status_code == 200

    claim_path = "/internal/whatsapp/reminder-notifications/claim"
    body = json.dumps({"limit": 10}).encode()
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as client:
        claim = await client.post(claim_path, content=body, headers=signed_for(claim_path, body))
        assert claim.status_code == 200
        [notification] = claim.json()["reminders"]
        assert notification["representative_phone_e164"] == REP_PHONE
        assert notification["customer_name"] == "Alfa Tecelagem Ltda."
        assert notification["origin"] == ReminderOrigin.CUSTOMER

        ack_path = "/internal/whatsapp/reminder-notifications/ack"
        ack_body = json.dumps({
            "reminder_id": notification["reminder_id"],
            "claim_token": notification["claim_token"],
            "delivered": True,
        }).encode()
        ack = await client.post(
            ack_path, content=ack_body, headers=signed_for(ack_path, ack_body)
        )
        assert ack.status_code == 200

        again = await client.post(
            claim_path, content=body, headers=signed_for(claim_path, body)
        )
        assert again.status_code == 200
        assert again.json()["reminders"] == []


@pytest.mark.asyncio
async def test_lembrete_pessoal_so_e_reservado_no_horario(world):
    now = datetime.now(UTC)
    async with world.app.state.session_factory() as session:
        session.add(
            RepresentativeReminder(
                id=uuid4(),
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                customer_id=None,
                customer_contact_id=None,
                origin=ReminderOrigin.REPRESENTATIVE.value,
                kind="FOLLOW_UP",
                status=ReminderStatus.CONFIRMED.value,
                note="Mandar mensagem para Patrick",
                due_at=now + timedelta(minutes=10),
                timezone="America/Sao_Paulo",
                source_wamid="wamid.PERSONAL.FUTURE",
                source_line_reference="assistant-line",
            )
        )
        await session.commit()

    claim_path = "/internal/whatsapp/reminder-notifications/claim"
    body = json.dumps({"limit": 10}).encode()
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as client:
        early = await client.post(claim_path, content=body, headers=signed_for(claim_path, body))
        assert early.status_code == 200
        assert early.json()["reminders"] == []

    async with world.app.state.session_factory() as session:
        reminder = await session.scalar(
            select(RepresentativeReminder).where(
                RepresentativeReminder.source_wamid == "wamid.PERSONAL.FUTURE"
            )
        )
        reminder.due_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as client:
        on_time = await client.post(claim_path, content=body, headers=signed_for(claim_path, body))
        assert on_time.status_code == 200
        [notification] = on_time.json()["reminders"]
        assert notification["origin"] == ReminderOrigin.REPRESENTATIVE
        assert notification["customer_name"] is None
