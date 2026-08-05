from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio
from conftest import (
    ADMIN_EMAIL,
    REPRESENTATIVE_A_EMAIL,
    REPRESENTATIVE_B_EMAIL,
    build_portal_world,
    login,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from crm_api.models.customer import Customer, CustomerAssignmentHistory
from crm_api.models.user import AuditLog, UserRole
from crm_api.repositories.portfolio import (
    CustomerFilters,
    CustomerPortfolioRepository,
    PortfolioScope,
)


@pytest_asyncio.fixture
async def world():
    built = await build_portal_world()
    yield built
    await built.app.state.engine.dispose()


@asynccontextmanager
async def _client(world, email: str):
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as client:
        await login(client, email=email)
        yield client


@pytest_asyncio.fixture
async def admin(world):
    async with _client(world, ADMIN_EMAIL) as client:
        yield client


@pytest_asyncio.fixture
async def representative_a(world):
    async with _client(world, REPRESENTATIVE_A_EMAIL) as client:
        yield client


@pytest.mark.asyncio
async def test_representative_sees_only_their_own_portfolio(world, representative_a):
    response = await representative_a.get("/admin/customers")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["customer_id"] for item in body["items"]] == [str(world.customer_a_id)]
    assert body["items"][0]["owner"]["full_name"] == "Vendedora A"


@pytest.mark.asyncio
async def test_admin_sees_the_whole_tenant_including_unassigned_customers(world, admin):
    response = await admin.get("/admin/customers")

    assert response.status_code == 200
    returned = {item["customer_id"] for item in response.json()["items"]}
    assert returned == {
        str(world.customer_a_id),
        str(world.customer_b_id),
        str(world.customer_unassigned_id),
    }


@pytest.mark.asyncio
async def test_customer_outside_the_portfolio_answers_not_found(world, representative_a):
    """Nunca `403`: confirmaria a existência da conta de outro representante."""
    response = await representative_a.get(f"/admin/customers/{world.customer_b_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "customer not found"

    absent = await representative_a.get(f"/admin/customers/{uuid4()}")
    assert absent.status_code == response.status_code
    assert absent.json()["detail"] == response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_opens_any_customer_of_the_tenant(world, admin):
    response = await admin.get(f"/admin/customers/{world.customer_b_id}")

    assert response.status_code == 200
    assert response.json()["legal_name"] == "Beta Malharia Ltda."


@pytest.mark.asyncio
async def test_me_customers_restricts_even_an_admin_to_their_own_portfolio(world, admin):
    response = await admin.get("/admin/me/customers")

    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_filters_narrow_the_listing(world, admin):
    by_state = await admin.get("/admin/customers?state_code=RS")
    by_product = await admin.get(f"/admin/customers?preferred_product_id={world.product_id}")
    unassigned = await admin.get("/admin/customers?assigned=false")
    by_search = await admin.get("/admin/customers?search=malharia")

    assert [item["customer_id"] for item in by_state.json()["items"]] == [
        str(world.customer_b_id)
    ]
    assert [item["customer_id"] for item in by_product.json()["items"]] == [
        str(world.customer_a_id)
    ]
    assert [item["customer_id"] for item in unassigned.json()["items"]] == [
        str(world.customer_unassigned_id)
    ]
    assert [item["customer_id"] for item in by_search.json()["items"]] == [
        str(world.customer_b_id)
    ]


@pytest.mark.asyncio
async def test_repository_alone_already_filters_by_portfolio(world):
    """O escopo não pode depender da rota nem do serviço.

    Uma rota nova que esqueça o filtro é o modo de falha realista; este teste
    fixa a garantia na camada que executa a consulta.
    """
    async with world.app.state.session_factory() as session:
        repository = CustomerPortfolioRepository(session)
        scope = PortfolioScope.for_user(
            tenant_id=world.tenant_id,
            user_id=world.representative_a_id,
            role=UserRole.REPRESENTATIVE,
        )

        rows = await repository.list_customers(scope, CustomerFilters(), limit=100, offset=0)
        foreign = await repository.get_customer(scope, world.customer_b_id)
        unassigned = await repository.get_customer(scope, world.customer_unassigned_id)

    assert [customer.id for customer, _ in rows] == [world.customer_a_id]
    assert foreign is None
    assert unassigned is None


@pytest.mark.asyncio
async def test_scope_for_manager_is_not_restricted_but_only_own_overrides_it(world):
    unrestricted = PortfolioScope.for_user(
        tenant_id=world.tenant_id, user_id=world.admin_id, role=UserRole.MANAGER
    )
    restricted = PortfolioScope.for_user(
        tenant_id=world.tenant_id,
        user_id=world.admin_id,
        role=UserRole.MANAGER,
        only_own=True,
    )

    assert unrestricted.owner_user_id is None
    assert restricted.owner_user_id == world.admin_id


@pytest.mark.asyncio
async def test_transfer_records_history_and_keeps_previous_rows_untouched(world, admin):
    first = await admin.put(
        f"/admin/customers/{world.customer_a_id}/owner",
        json={"owner_user_id": str(world.representative_b_id), "reason": "férias"},
    )
    second = await admin.put(
        f"/admin/customers/{world.customer_a_id}/owner",
        json={"owner_user_id": str(world.representative_a_id), "reason": "retorno"},
    )

    assert first.status_code == 200
    assert first.json()["owner"]["full_name"] == "Vendedor B"
    assert second.json()["owner"]["full_name"] == "Vendedora A"

    history = await admin.get(f"/admin/customers/{world.customer_a_id}/assignment-history")
    entries = history.json()

    assert [entry["reason"] for entry in entries] == ["retorno", "férias"]
    assert entries[0]["owner"]["full_name"] == "Vendedora A"
    assert entries[1]["owner"]["full_name"] == "Vendedor B"
    assert all(entry["assigned_by"] == str(world.admin_id) for entry in entries)


@pytest.mark.asyncio
async def test_reassigning_the_same_owner_writes_no_history(world, admin):
    response = await admin.put(
        f"/admin/customers/{world.customer_a_id}/owner",
        json={"owner_user_id": str(world.representative_a_id)},
    )

    assert response.status_code == 200

    async with world.app.state.session_factory() as session:
        entries = list(await session.scalars(select(CustomerAssignmentHistory)))

    assert entries == []


@pytest.mark.asyncio
async def test_removing_the_owner_is_recorded_as_an_event(world, admin):
    response = await admin.put(
        f"/admin/customers/{world.customer_a_id}/owner",
        json={"owner_user_id": None, "reason": "desligamento"},
    )

    assert response.status_code == 200
    assert response.json()["owner"] is None

    async with world.app.state.session_factory() as session:
        entry = await session.scalar(select(CustomerAssignmentHistory))
        audited = await session.scalar(
            select(AuditLog).where(AuditLog.action == "CUSTOMER_OWNER_REMOVED")
        )

    assert entry.user_id is None
    assert entry.reason == "desligamento"
    assert audited.before["owner_user_id"] == str(world.representative_a_id)
    assert audited.after["owner_user_id"] is None


@pytest.mark.asyncio
async def test_owner_must_be_an_active_user_of_the_tenant(world, admin):
    inactive = await admin.put(
        f"/admin/customers/{world.customer_a_id}/owner",
        json={"owner_user_id": str(world.inactive_user_id)},
    )
    absent = await admin.put(
        f"/admin/customers/{world.customer_a_id}/owner",
        json={"owner_user_id": str(uuid4())},
    )

    assert inactive.status_code == absent.status_code == 422

    async with world.app.state.session_factory() as session:
        customer = await session.scalar(
            select(Customer).where(Customer.id == world.customer_a_id)
        )

    assert customer.owner_user_id == world.representative_a_id


@pytest.mark.asyncio
async def test_representative_cannot_transfer_or_read_the_assignment_history(
    world, representative_a
):
    transfer = await representative_a.put(
        f"/admin/customers/{world.customer_a_id}/owner",
        json={"owner_user_id": str(world.representative_b_id)},
    )
    history = await representative_a.get(
        f"/admin/customers/{world.customer_a_id}/assignment-history"
    )

    assert transfer.status_code == history.status_code == 403
    assert transfer.json()["detail"] == "insufficient role"


@pytest.mark.asyncio
async def test_portfolio_requires_authentication(world):
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as anonymous:
        response = await anonymous.get("/admin/customers")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_representative_b_reaches_only_their_own_customer(world):
    async with _client(world, REPRESENTATIVE_B_EMAIL) as client:
        listing = await client.get("/admin/customers")
        own = await client.get(f"/admin/customers/{world.customer_b_id}")

    assert [item["customer_id"] for item in listing.json()["items"]] == [
        str(world.customer_b_id)
    ]
    assert own.status_code == 200
