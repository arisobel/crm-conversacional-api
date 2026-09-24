from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.user import User
from crm_api.models.whatsapp_connection import RepresentativeWhatsappConnection
from crm_api.services.gateway_whatsapp_onboarding import (
    GatewayOnboarding,
    GatewayWhatsappOnboardingClient,
)
from tests.conftest import (
    ADMIN_EMAIL,
    REPRESENTATIVE_A_EMAIL,
    build_portal_world,
    login,
)


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def gateway(monkeypatch):
    state = {
        "status": "AUTHORIZATION_PENDING",
        "resume_status": None,
        "failure_code": None,
        "onboarding_number": 0,
        "resume_calls": 0,
    }

    async def create(self, **_):
        state["onboarding_number"] += 1
        onboarding_id = f"ob-{state['onboarding_number']}"
        return GatewayOnboarding(
            onboarding_id,
            state["status"],
            f"/meta/whatsapp/onboardings/{onboarding_id}/launch",
        )

    async def get(self, _):
        return GatewayOnboarding(
            f"ob-{state['onboarding_number']}",
            state["status"],
            failure_code=state["failure_code"],
            display_phone_number="+5511999999999",
            gateway_line_reference="line-1",
        )

    async def resume(self, _, **__):
        state["resume_calls"] += 1
        state["status"] = state["resume_status"] or "AUTHORIZATION_PENDING"
        return GatewayOnboarding(f"ob-{state['onboarding_number']}", state["status"])

    monkeypatch.setattr(GatewayWhatsappOnboardingClient, "create_onboarding", create)
    monkeypatch.setattr(GatewayWhatsappOnboardingClient, "get_onboarding", get)
    monkeypatch.setattr(GatewayWhatsappOnboardingClient, "resume_onboarding", resume)
    return state


async def _csrf(client):
    await client.get("/portal/customers")
    return client.cookies.get("crm_csrf")


@pytest.mark.asyncio
async def test_representative_starts_own_connection_and_polling_projects_completed(gateway):
    world = await build_portal_world(whatsapp_gateway_base_url="https://gateway.test")
    async with await _client(world.app) as client:
        await login(client, email=REPRESENTATIVE_A_EMAIL)
        csrf = await _csrf(client)
        path = f"/api/v1/representatives/{world.representative_a_id}/whatsapp-connection"
        created = await client.post(path, headers={"X-CSRF-Token": csrf})
        assert created.status_code == 201
        assert created.json()["status"] == "CONNECTING"
        assert (
            created.json()["launch_url"]
            == "https://gateway.test/meta/whatsapp/onboardings/ob-1/launch"
        )

        gateway["status"] = "COMPLETED"
        resolved = await client.get(path)
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "CONNECTED"
        assert resolved.json()["display_phone_number"] == "+5511999999999"


@pytest.mark.asyncio
async def test_representative_cannot_read_or_start_another_representative_connection(gateway):
    world = await build_portal_world(whatsapp_gateway_base_url="https://gateway.test")
    async with await _client(world.app) as client:
        await login(client, email=REPRESENTATIVE_A_EMAIL)
        csrf = await _csrf(client)
        path = f"/api/v1/representatives/{world.representative_b_id}/whatsapp-connection"
        assert (await client.get(path)).status_code == 403
        assert (await client.post(path, headers={"X-CSRF-Token": csrf})).status_code == 403


@pytest.mark.asyncio
async def test_admin_can_manage_same_tenant_and_repeated_start_is_not_a_second_onboarding(gateway):
    world = await build_portal_world(whatsapp_gateway_base_url="https://gateway.test")
    async with await _client(world.app) as client:
        await login(client, email=ADMIN_EMAIL)
        csrf = await _csrf(client)
        path = f"/api/v1/representatives/{world.representative_a_id}/whatsapp-connection"
        assert (await client.post(path, headers={"X-CSRF-Token": csrf})).status_code == 201
        assert (await client.post(path, headers={"X-CSRF-Token": csrf})).status_code == 409
        assert (
            await client.get(f"/api/v1/representatives/{uuid4()}/whatsapp-connection")
        ).status_code == 404


@pytest.mark.asyncio
async def test_action_required_can_resume(gateway):
    world = await build_portal_world(whatsapp_gateway_base_url="https://gateway.test")
    async with await _client(world.app) as client:
        await login(client, email=REPRESENTATIVE_A_EMAIL)
        csrf = await _csrf(client)
        path = f"/api/v1/representatives/{world.representative_a_id}/whatsapp-connection"
        await client.post(path, headers={"X-CSRF-Token": csrf})
        gateway["status"] = "ACTION_REQUIRED"
        assert (await client.get(path)).json()["status"] == "ACTION_REQUIRED"
        resumed = await client.post(f"{path}/resume", headers={"X-CSRF-Token": csrf})
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "CONNECTING"
        assert resumed.json()["launch_url"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gateway_status", "expected_status"),
    [
        ("COMPLETED", "CONNECTED"),
        ("ACTION_REQUIRED", "ACTION_REQUIRED"),
        ("CONFLICT", "CONFLICT"),
        ("FAILED", "FAILED"),
    ],
)
async def test_resume_without_launch_url_projects_gateway_terminal_state(
    gateway, gateway_status, expected_status
):
    world = await build_portal_world(whatsapp_gateway_base_url="https://gateway.test")
    async with await _client(world.app) as client:
        await login(client, email=REPRESENTATIVE_A_EMAIL)
        csrf = await _csrf(client)
        path = f"/api/v1/representatives/{world.representative_a_id}/whatsapp-connection"
        await client.post(path, headers={"X-CSRF-Token": csrf})
        gateway["status"] = "ACTION_REQUIRED"
        await client.get(path)
        gateway["resume_status"] = gateway_status

        resumed = await client.post(f"{path}/resume", headers={"X-CSRF-Token": csrf})

        assert resumed.status_code == 200
        assert resumed.json()["status"] == expected_status
        assert resumed.json()["launch_url"] is None


@pytest.mark.asyncio
async def test_token_exchange_rejected_creates_a_new_attempt_for_the_same_representative(gateway):
    world = await build_portal_world(whatsapp_gateway_base_url="https://gateway.test")
    async with await _client(world.app) as client:
        await login(client, email=REPRESENTATIVE_A_EMAIL)
        csrf = await _csrf(client)
        path = f"/api/v1/representatives/{world.representative_a_id}/whatsapp-connection"
        first = await client.post(path, headers={"X-CSRF-Token": csrf})
        assert first.json()["launch_url"].endswith("ob-1/launch")

        gateway["status"] = "FAILED"
        gateway["failure_code"] = "TOKEN_EXCHANGE_REJECTED"
        failed = await client.get(path)
        assert failed.json()["retry_action"] == "RESTART"

        gateway["status"] = "AUTHORIZATION_PENDING"
        gateway["failure_code"] = None
        restarted = await client.post(path, headers={"X-CSRF-Token": csrf})
        assert restarted.status_code == 201
        assert restarted.json()["status"] == "CONNECTING"
        assert restarted.json()["representative_user_id"] == str(world.representative_a_id)
        assert restarted.json()["launch_url"].endswith("ob-2/launch")
        assert gateway["resume_calls"] == 0

    async with world.app.state.session_factory() as session:
        attempts = list(
            await session.scalars(
                select(RepresentativeWhatsappConnection)
                .where(
                    RepresentativeWhatsappConnection.representative_user_id
                    == world.representative_a_id
                )
                .order_by(RepresentativeWhatsappConnection.created_at)
            )
        )
    assert len(attempts) == 2
    assert attempts[0].failure_code == "TOKEN_EXCHANGE_REJECTED"
    assert attempts[0].gateway_onboarding_id != attempts[1].gateway_onboarding_id
    assert attempts[0].idempotency_key != attempts[1].idempotency_key
    assert all(attempt.representative_user_id == world.representative_a_id for attempt in attempts)
    async with world.app.state.session_factory() as session:
        representative = await session.scalar(
            select(User).where(User.id == world.representative_a_id)
        )
    assert representative is not None
    assert representative.email == REPRESENTATIVE_A_EMAIL
    assert representative.whatsapp_e164 is None


@pytest.mark.asyncio
async def test_recoverable_failed_connection_must_resume_instead_of_starting_another(gateway):
    world = await build_portal_world(whatsapp_gateway_base_url="https://gateway.test")
    async with await _client(world.app) as client:
        await login(client, email=REPRESENTATIVE_A_EMAIL)
        csrf = await _csrf(client)
        path = f"/api/v1/representatives/{world.representative_a_id}/whatsapp-connection"
        await client.post(path, headers={"X-CSRF-Token": csrf})
        gateway["status"] = "FAILED"
        gateway["failure_code"] = "TRANSIENT_GATEWAY_FAILURE"
        failed = await client.get(path)
        assert failed.json()["retry_action"] == "RESUME"
        assert (await client.post(path, headers={"X-CSRF-Token": csrf})).status_code == 409

        resumed = await client.post(f"{path}/resume", headers={"X-CSRF-Token": csrf})
        assert resumed.status_code == 200
        assert gateway["resume_calls"] == 1
