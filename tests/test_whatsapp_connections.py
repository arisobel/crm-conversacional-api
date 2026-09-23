from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

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
    state = {"status": "AUTHORIZATION_PENDING", "resume_status": None}

    async def create(self, **_):
        return GatewayOnboarding("ob-1", state["status"], "/meta/whatsapp/onboardings/ob-1/launch")

    async def get(self, _):
        return GatewayOnboarding(
            "ob-1",
            state["status"],
            display_phone_number="+5511999999999",
            gateway_line_reference="line-1",
        )

    async def resume(self, _, **__):
        state["status"] = state["resume_status"] or "AUTHORIZATION_PENDING"
        return GatewayOnboarding("ob-1", state["status"])

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
