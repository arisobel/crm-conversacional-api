from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.api.authentication import CurrentUser, require_roles
from crm_api.core.config import Settings
from crm_api.core.passwords import WeakPassword, hash_password, validate_password_policy
from crm_api.main import create_app
from crm_api.models.base import Base
from crm_api.models.customer import Tenant
from crm_api.models.user import AuditLog, User, UserRole, UserSession

PASSWORD = "SenhaForte12345"
ADMIN_EMAIL = "gestora@teste.com.br"
REPRESENTATIVE_EMAIL = "vendedor@teste.com.br"
INACTIVE_EMAIL = "desligado@teste.com.br"


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite://",
        "tenant_slug": "test-tenant",
        "internal_hmac_secret": "test-secret",
        # O cliente de teste fala HTTP; um cookie `Secure` não seria armazenado.
        "session_cookie_secure": False,
    }
    values.update(overrides)
    return Settings(**values)


async def _build_app(**overrides):
    application = create_app(_settings(**overrides))
    async with application.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    tenant = Tenant(id=uuid4(), name="Tenant de teste", slug="test-tenant")
    password_hash = hash_password(PASSWORD)
    users = [
        User(
            id=uuid4(),
            tenant_id=tenant.id,
            full_name="Gestora Exemplo",
            email=ADMIN_EMAIL,
            password_hash=password_hash,
            role=UserRole.ADMIN,
        ),
        User(
            id=uuid4(),
            tenant_id=tenant.id,
            full_name="Vendedor Exemplo",
            email=REPRESENTATIVE_EMAIL,
            password_hash=password_hash,
            role=UserRole.REPRESENTATIVE,
        ),
        User(
            id=uuid4(),
            tenant_id=tenant.id,
            full_name="Desligado Exemplo",
            email=INACTIVE_EMAIL,
            password_hash=password_hash,
            role=UserRole.REPRESENTATIVE,
            active=False,
        ),
    ]
    async with application.state.session_factory() as session:
        session.add_all([tenant, *users])
        await session.commit()
    return application


@pytest_asyncio.fixture
async def app():
    application = await _build_app()
    yield application
    await application.state.engine.dispose()


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client


async def _login(client, *, email: str = ADMIN_EMAIL, password: str = PASSWORD):
    return await client.post("/admin/auth/login", json={"email": email, "password": password})


@pytest.mark.asyncio
async def test_login_issues_http_only_session_cookie(client):
    response = await _login(client)

    assert response.status_code == 200
    assert response.json()["email"] == ADMIN_EMAIL
    assert response.json()["role"] == "ADMIN"
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header
    assert PASSWORD not in cookie_header


@pytest.mark.asyncio
async def test_login_normalizes_email_case_and_padding(client):
    response = await _login(client, email=f"  {ADMIN_EMAIL.upper()}  ")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_login_does_not_reveal_whether_the_email_exists(client):
    unknown = await _login(client, email="ninguem@teste.com.br")
    wrong_password = await _login(client, password="OutraSenha12345")

    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json()["detail"] == wrong_password.json()["detail"] == "invalid credentials"
    assert unknown.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_inactive_user_cannot_log_in(client):
    response = await _login(client, email=INACTIVE_EMAIL)

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_account_locks_after_repeated_failures_even_with_the_right_password(app, client):
    for _ in range(app.state.settings.login_max_failed_attempts):
        assert (await _login(client, password="SenhaErrada12345")).status_code == 401

    assert (await _login(client)).status_code == 401

    async with app.state.session_factory() as session:
        user = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert user.locked_until is not None
        assert user.failed_login_attempts >= app.state.settings.login_max_failed_attempts


@pytest.mark.asyncio
async def test_login_rate_limit_stops_attempts_before_reaching_the_database():
    application = await _build_app(login_rate_limit_attempts=2)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            first = await _login(client, email="ninguem@teste.com.br")
            second = await _login(client, email="ninguem@teste.com.br")
            third = await _login(client, email="ninguem@teste.com.br")

        assert first.status_code == second.status_code == 401
        assert third.status_code == 429
        assert third.json()["detail"] == "too many login attempts"
    finally:
        await application.state.engine.dispose()


@pytest.mark.asyncio
async def test_me_requires_a_session(client):
    response = await client.get("/admin/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "authentication required"


@pytest.mark.asyncio
async def test_me_returns_the_authenticated_user(client):
    await _login(client, email=REPRESENTATIVE_EMAIL)

    response = await client.get("/admin/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == REPRESENTATIVE_EMAIL
    assert response.json()["role"] == "REPRESENTATIVE"


@pytest.mark.asyncio
async def test_logout_revokes_the_session_for_a_stolen_cookie(app, client):
    await _login(client)
    token = client.cookies.get(app.state.settings.session_cookie_name)

    assert (await client.post("/admin/auth/logout")).status_code == 204

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={app.state.settings.session_cookie_name: token},
    ) as replayed:
        response = await replayed.get("/admin/auth/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_deactivating_a_user_invalidates_issued_sessions(app, client):
    await _login(client)
    assert (await client.get("/admin/auth/me")).status_code == 200

    async with app.state.session_factory() as session:
        user = await session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        user.active = False
        await session.commit()

    assert (await client.get("/admin/auth/me")).status_code == 401

    async with app.state.session_factory() as session:
        revoked = await session.scalar(
            select(UserSession).where(UserSession.user_id == user.id)
        )
        assert revoked.revoked_at is not None


@pytest.mark.asyncio
async def test_session_token_is_never_stored_in_clear_text(app, client):
    await _login(client)
    token = client.cookies.get(app.state.settings.session_cookie_name)

    async with app.state.session_factory() as session:
        stored = await session.scalar(select(UserSession))

    assert stored.token_hash != token
    assert len(stored.token_hash) == 64


@pytest.mark.asyncio
async def test_audit_trail_records_success_and_failure(app, client):
    await _login(client, password="SenhaErrada12345")
    await _login(client, email="ninguem@teste.com.br")
    await _login(client)

    async with app.state.session_factory() as session:
        entries = list(await session.scalars(select(AuditLog).order_by(AuditLog.action)))

    recorded = {entry.action for entry in entries}
    assert recorded == {"LOGIN_FAILED", "LOGIN_SUCCEEDED"}

    unknown_email_entry = next(
        entry
        for entry in entries
        if entry.action == "LOGIN_FAILED" and entry.after.get("reason") == "UNKNOWN_EMAIL"
    )
    assert unknown_email_entry.tenant_id is None
    assert unknown_email_entry.actor_user_id is None
    assert all(PASSWORD not in str(entry.after) for entry in entries)


@pytest.mark.asyncio
async def test_require_roles_allows_only_the_listed_roles():
    representative = CurrentUser(
        session_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        full_name="Vendedor Exemplo",
        email=REPRESENTATIVE_EMAIL,
        role=UserRole.REPRESENTATIVE,
    )

    assert await require_roles(UserRole.REPRESENTATIVE)(representative) is representative

    with pytest.raises(HTTPException) as error:
        await require_roles(UserRole.ADMIN, UserRole.MANAGER)(representative)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_gateway_hmac_does_not_open_the_portal(client):
    """O esquema interno do Gateway não concede sessão nem papel."""
    response = await client.get(
        "/admin/auth/me",
        headers={"X-Tenant-Slug": "test-tenant", "X-Timestamp": "x", "X-Signature": "y"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "password",
    ["curta1", "senhasemnumero", "123456789012345", "gestora12345678"],
)
def test_password_policy_rejects_weak_passwords(password):
    with pytest.raises(WeakPassword):
        validate_password_policy(password, email=ADMIN_EMAIL, min_length=12)


def test_password_policy_accepts_a_compliant_password():
    validate_password_policy(PASSWORD, email=ADMIN_EMAIL, min_length=12)
