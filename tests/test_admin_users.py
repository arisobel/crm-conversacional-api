from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import (
    ADMIN_EMAIL,
    PASSWORD,
    REPRESENTATIVE_A_EMAIL,
    build_portal_world,
    login,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.user import AuditLog, User, UserSession

NEW_PASSWORD = "OutraSenhaBoa2026"


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    yield built
    await built.app.state.engine.dispose()


@asynccontextmanager
async def _client(world, email: str | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as client:
        if email is not None:
            await login(client, email=email)
        yield client


@pytest_asyncio.fixture
async def admin(world):
    async with _client(world, ADMIN_EMAIL) as client:
        yield client


@pytest.mark.asyncio
async def test_admin_creates_a_representative(world, admin):
    response = await admin.post(
        "/admin/users",
        json={
            "full_name": "Novo Vendedor",
            "email": "Novo.Vendedor@Teste.com.BR",
            "password": NEW_PASSWORD,
            "role": "REPRESENTATIVE",
            "whatsapp_e164": "+5511999999999",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "novo.vendedor@teste.com.br"
    assert body["role"] == "REPRESENTATIVE"
    assert "password" not in body
    assert "password_hash" not in body

    async with _client(world) as anonymous:
        signed_in = await login(
            anonymous, email="novo.vendedor@teste.com.br", password=NEW_PASSWORD
        )
    assert signed_in.status_code == 200


@pytest.mark.asyncio
async def test_representative_cannot_manage_users(world):
    async with _client(world, REPRESENTATIVE_A_EMAIL) as client:
        listing = await client.get("/admin/users")
        creation = await client.post(
            "/admin/users",
            json={"full_name": "X", "email": "x@teste.com.br", "password": NEW_PASSWORD},
        )

    assert listing.status_code == creation.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_email_is_rejected(admin):
    response = await admin.post(
        "/admin/users",
        json={"full_name": "Duplicada", "email": ADMIN_EMAIL, "password": NEW_PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "email already used"


@pytest.mark.asyncio
async def test_weak_password_is_rejected_before_the_user_exists(world, admin):
    response = await admin.post(
        "/admin/users",
        json={"full_name": "Fraca", "email": "fraca@teste.com.br", "password": "curta1"},
    )

    assert response.status_code == 422

    async with world.app.state.session_factory() as session:
        created = await session.scalar(select(User).where(User.email == "fraca@teste.com.br"))
    assert created is None


@pytest.mark.asyncio
async def test_listing_filters_by_role_and_status(world, admin):
    representatives = await admin.get("/admin/users?role=REPRESENTATIVE")
    active_only = await admin.get("/admin/users?role=REPRESENTATIVE&active=true")

    assert representatives.json()["total"] == 3
    assert active_only.json()["total"] == 2
    assert all(item["role"] == "REPRESENTATIVE" for item in active_only.json()["items"])


@pytest.mark.asyncio
async def test_deactivating_a_user_revokes_their_open_session(world, admin):
    async with _client(world, REPRESENTATIVE_A_EMAIL) as representative:
        assert (await representative.get("/admin/auth/me")).status_code == 200

        response = await admin.post(f"/admin/users/{world.representative_a_id}/deactivate")
        assert response.status_code == 200
        assert response.json()["active"] is False

        assert (await representative.get("/admin/auth/me")).status_code == 401

    async with world.app.state.session_factory() as session:
        session_row = await session.scalar(
            select(UserSession).where(UserSession.user_id == world.representative_a_id)
        )
    assert session_row.revoked_at is not None


@pytest.mark.asyncio
async def test_a_user_cannot_deactivate_their_own_account(world, admin):
    response = await admin.post(f"/admin/users/{world.admin_id}/deactivate")

    assert response.status_code == 422
    assert response.json()["detail"] == "a user cannot deactivate their own account"


@pytest.mark.asyncio
async def test_the_last_active_admin_cannot_be_demoted_or_deactivated(world, admin):
    """Sem esta guarda, uma alteração tranca todos para fora do portal."""
    other_admin = await admin.post(
        "/admin/users",
        json={
            "full_name": "Segundo Admin",
            "email": "segundo@teste.com.br",
            "password": NEW_PASSWORD,
            "role": "ADMIN",
        },
    )
    other_admin_id = other_admin.json()["user_id"]

    demote_blocked = await admin.patch(
        f"/admin/users/{world.admin_id}", json={"role": "REPRESENTATIVE"}
    )
    assert demote_blocked.status_code == 200

    async with _client(world) as anonymous:
        await login(anonymous, email="segundo@teste.com.br", password=NEW_PASSWORD)
        demote_last = await anonymous.patch(
            f"/admin/users/{other_admin_id}", json={"role": "REPRESENTATIVE"}
        )
        deactivate_last = await anonymous.post(f"/admin/users/{other_admin_id}/deactivate")

    assert demote_last.status_code == 422
    assert "last active ADMIN" in demote_last.json()["detail"]
    # Autodesativação é barrada antes da guarda do último ADMIN.
    assert deactivate_last.status_code == 422


@pytest.mark.asyncio
async def test_reactivating_a_user_restores_access(world, admin):
    await admin.post(f"/admin/users/{world.representative_a_id}/deactivate")
    response = await admin.post(f"/admin/users/{world.representative_a_id}/activate")

    assert response.status_code == 200
    assert response.json()["active"] is True

    async with _client(world) as anonymous:
        assert (await login(anonymous, email=REPRESENTATIVE_A_EMAIL)).status_code == 200


@pytest.mark.asyncio
async def test_password_reset_revokes_sessions_and_replaces_the_credential(world, admin):
    async with _client(world, REPRESENTATIVE_A_EMAIL) as representative:
        response = await admin.post(
            f"/admin/users/{world.representative_a_id}/password",
            json={"password": NEW_PASSWORD},
        )
        assert response.status_code == 200
        assert (await representative.get("/admin/auth/me")).status_code == 401

    async with _client(world) as anonymous:
        old = await login(anonymous, email=REPRESENTATIVE_A_EMAIL, password=PASSWORD)
        new = await login(anonymous, email=REPRESENTATIVE_A_EMAIL, password=NEW_PASSWORD)

    assert old.status_code == 401
    assert new.status_code == 200


@pytest.mark.asyncio
async def test_unknown_user_answers_not_found(admin):
    absent = uuid4()

    assert (await admin.get(f"/admin/users/{absent}")).status_code == 404
    assert (await admin.patch(f"/admin/users/{absent}", json={"full_name": "X"})).status_code == 404
    assert (await admin.post(f"/admin/users/{absent}/deactivate")).status_code == 404


@pytest.mark.asyncio
async def test_user_management_is_audited(world, admin):
    created = await admin.post(
        "/admin/users",
        json={
            "full_name": "Auditada",
            "email": "auditada@teste.com.br",
            "password": NEW_PASSWORD,
        },
    )
    await admin.patch(
        f"/admin/users/{created.json()['user_id']}", json={"full_name": "Auditada Silva"}
    )
    await admin.post(f"/admin/users/{created.json()['user_id']}/deactivate")

    async with world.app.state.session_factory() as session:
        entries = list(await session.scalars(select(AuditLog)))

    recorded = {entry.action for entry in entries}
    assert {"USER_CREATED", "USER_UPDATED", "USER_DEACTIVATED"} <= recorded
    assert all(NEW_PASSWORD not in str(entry.after) for entry in entries)
    assert all(
        entry.actor_user_id == world.admin_id
        for entry in entries
        if entry.action.startswith("USER_")
    )
