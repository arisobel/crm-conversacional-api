import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.assistant_settings import (
    AssistantOrganizationSettings,
    AssistantRepresentativeCapability,
    AssistantRepresentativeSettings,
)
from crm_api.models.user import (
    RepresentativeInvite,
    RepresentativeInviteStatus,
    User,
    UserRole,
)
from tests.conftest import ADMIN_EMAIL, PASSWORD, build_portal_world

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
_INVITE = re.compile(r'value="(http://test/portal/convite/representante/[^\"]+)"')


def _token(html: str) -> str:
    found = _CSRF.search(html)
    assert found
    return found.group(1)


async def _login(client: AsyncClient) -> None:
    page = await client.get("/portal/login")
    response = await client.post(
        "/portal/login",
        data={"email": ADMIN_EMAIL, "password": PASSWORD, "csrf_token": _token(page.text)},
    )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_admin_generates_single_use_invite_and_representative_activates_it():
    world = await build_portal_world(assistant_line_phone_number_id="1385749677954761")
    try:
        async with world.app.state.session_factory() as session:
            session.add(
                AssistantOrganizationSettings(tenant_id=world.tenant_id, enabled=True)
            )
            await session.commit()
        async with AsyncClient(
            transport=ASGITransport(app=world.app),
            base_url="http://test",
            follow_redirects=False,
        ) as admin:
            await _login(admin)
            portfolio = await admin.get("/portal/customers")
            assert "Convidar representante" in portfolio.text
            created = await admin.post(
                "/portal/representative-invites",
                data={"csrf_token": _token(portfolio.text)},
            )
            assert created.status_code == 200
            found_link = _INVITE.search(created.text)
            assert found_link
            invite_url = found_link.group(1)

        async with AsyncClient(
            transport=ASGITransport(app=world.app),
            base_url="http://test",
            follow_redirects=False,
        ) as representative:
            invite_page = await representative.get(invite_url)
            assert invite_page.status_code == 200
            assert "Prepare seu acesso ao CRM" in invite_page.text
            accepted = await representative.post(
                invite_url,
                data={
                    "csrf_token": _token(invite_page.text),
                    "full_name": "Nova Representante",
                    "email": "nova.representante@teste.com.br",
                    "whatsapp_e164": "+55 11 98888-7766",
                    "password": "ConviteForte98765",
                },
            )
            assert accepted.status_code == 303
            assert accepted.headers["location"] == "/portal/onboarding/representante"
            assert representative.cookies.get("crm_session")

            ready = await representative.get(accepted.headers["location"])
            assert ready.status_code == 200
            assert "Seus dados já estão no CRM" in ready.text
            assert "Conectar meu WhatsApp Business" in ready.text
            assert "Seu número já foi autorizado" in ready.text

        async with world.app.state.session_factory() as session:
            created_user = await session.scalar(
                select(User).where(User.email == "nova.representante@teste.com.br")
            )
            assert created_user is not None
            assert created_user.role is UserRole.REPRESENTATIVE
            assert created_user.whatsapp_e164 == "+5511988887766"
            invite = await session.scalar(select(RepresentativeInvite))
            assert invite is not None
            assert invite.status is RepresentativeInviteStatus.ACCEPTED
            assert invite.representative_user_id == created_user.id
            assistant = await session.get(
                AssistantRepresentativeSettings,
                (world.tenant_id, created_user.id),
            )
            assert assistant is not None and assistant.enabled
            capabilities = set(
                await session.scalars(
                    select(AssistantRepresentativeCapability.capability_id).where(
                        AssistantRepresentativeCapability.tenant_id == world.tenant_id,
                        AssistantRepresentativeCapability.user_id == created_user.id,
                    )
                )
            )
            assert "CRM_REP_CREATE_REMINDER" in capabilities

        async with AsyncClient(
            transport=ASGITransport(app=world.app), base_url="http://test"
        ) as another_browser:
            reused = await another_browser.get(invite_url)
            assert reused.status_code == 410
            assert "não está mais disponível" in reused.text
    finally:
        await world.app.state.engine.dispose()


@pytest.mark.asyncio
async def test_representative_does_not_receive_invite_generation_button():
    world = await build_portal_world()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=world.app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            login_page = await client.get("/portal/login")
            await client.post(
                "/portal/login",
                data={
                    "email": "vendedora@teste.com.br",
                    "password": PASSWORD,
                    "csrf_token": _token(login_page.text),
                },
            )
            portfolio = await client.get("/portal/customers")
            assert "Convidar representante" not in portfolio.text
    finally:
        await world.app.state.engine.dispose()
