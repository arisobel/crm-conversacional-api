from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from conftest import ADMIN_EMAIL, REPRESENTATIVE_A_EMAIL, build_portal_world, login
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crm_api.core.states import BRAZILIAN_STATES, InvalidStateCode, normalize_state_code
from crm_api.models.customer import Customer, CustomerAssignmentHistory, CustomerLocation
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import AuditLog


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
async def representative(world):
    async with _client(world, REPRESENTATIVE_A_EMAIL) as client:
        yield client


# --------------------------------------------------------------------- UFs


def test_all_twenty_seven_states_are_listed():
    assert len(BRAZILIAN_STATES) == 27


def test_state_code_is_normalized_and_validated():
    assert normalize_state_code(" sp ") == "SP"
    with pytest.raises(InvalidStateCode):
        normalize_state_code("XX")


# ----------------------------------------------------------------- cliente


@pytest.mark.asyncio
async def test_admin_creates_a_customer_with_its_default_location(world, admin):
    response = await admin.post(
        "/admin/customers",
        json={
            "legal_name": "Delta Fiação Ltda.",
            "state_code": "mg",
            "trade_name": "Delta",
            "document_number": "22222222000122",
            "owner_user_id": str(world.representative_b_id),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["state_code"] == "MG"
    assert body["owner"]["full_name"] == "Vendedor B"

    locations = await admin.get(f"/admin/customers/{body['customer_id']}/locations")
    assert [
        (item["label"], item["state_code"], item["is_default"])
        for item in locations.json()
    ] == [("Principal", "MG", True)]


@pytest.mark.asyncio
async def test_representative_creating_a_customer_becomes_its_owner(world, representative):
    """`owner_user_id` do corpo é ignorado para quem não pode escolher titular."""
    response = await representative.post(
        "/admin/customers",
        json={
            "legal_name": "Epsilon Têxtil Ltda.",
            "state_code": "SP",
            "owner_user_id": str(world.representative_b_id),
        },
    )

    assert response.status_code == 201
    assert response.json()["owner"]["user_id"] == str(world.representative_a_id)

    async with world.app.state.session_factory() as session:
        entry = await session.scalar(
            select(CustomerAssignmentHistory).where(
                CustomerAssignmentHistory.customer_id == UUID(response.json()["customer_id"])
            )
        )
    assert entry.user_id == world.representative_a_id
    assert entry.reason == "cadastro inicial"


@pytest.mark.asyncio
async def test_invalid_state_and_duplicate_document_are_refused(world, admin):
    invalid_state = await admin.post(
        "/admin/customers", json={"legal_name": "Zeta", "state_code": "XX"}
    )
    await admin.post(
        "/admin/customers",
        json={"legal_name": "Eta", "state_code": "SP", "document_number": "33333333000133"},
    )
    duplicate = await admin.post(
        "/admin/customers",
        json={"legal_name": "Theta", "state_code": "SP", "document_number": "33333333000133"},
    )

    assert invalid_state.status_code == 422
    assert "not a Brazilian state code" in invalid_state.json()["detail"]
    assert duplicate.status_code == 409

    async with world.app.state.session_factory() as session:
        refused = await session.scalar(select(Customer).where(Customer.legal_name == "Zeta"))
    assert refused is None


@pytest.mark.asyncio
async def test_customer_can_be_edited_and_deactivated(world, admin):
    response = await admin.patch(
        f"/admin/customers/{world.customer_a_id}",
        json={"trade_name": "Alfa Têxtil", "state_code": "PR", "active": False},
    )

    assert response.status_code == 200
    assert response.json()["trade_name"] == "Alfa Têxtil"
    assert response.json()["state_code"] == "PR"
    assert response.json()["active"] is False


@pytest.mark.asyncio
async def test_representative_cannot_edit_a_customer_outside_the_portfolio(
    world, representative
):
    response = await representative.patch(
        f"/admin/customers/{world.customer_b_id}", json={"trade_name": "Invadida"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "customer not found"


# ---------------------------------------------------------------- contatos


@pytest.mark.asyncio
async def test_contact_is_created_with_a_normalized_phone(world, admin):
    response = await admin.post(
        f"/admin/customers/{world.customer_a_id}/contacts",
        json={"name": "Vitória Exemplo", "whatsapp_e164": "+55 (11) 99999-9999"},
    )

    assert response.status_code == 201
    assert response.json()["whatsapp_e164"] == "+5511999999999"


@pytest.mark.asyncio
async def test_duplicate_phone_within_the_tenant_is_refused(world, admin):
    payload = {"name": "Primeiro", "whatsapp_e164": "+5511988887777"}
    first = await admin.post(f"/admin/customers/{world.customer_a_id}/contacts", json=payload)
    second = await admin.post(
        f"/admin/customers/{world.customer_b_id}/contacts",
        json={"name": "Segundo", "whatsapp_e164": "+5511988887777"},
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "whatsapp already used"


@pytest.mark.asyncio
async def test_invalid_phone_is_refused(world, admin):
    response = await admin.post(
        f"/admin/customers/{world.customer_a_id}/contacts",
        json={"name": "Sem DDI", "whatsapp_e164": "5511999990000"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_marking_a_new_primary_contact_unmarks_the_previous_one(world, admin):
    first = await admin.post(
        f"/admin/customers/{world.customer_a_id}/contacts",
        json={"name": "Primeira", "whatsapp_e164": "+5511911111111", "is_primary": True},
    )
    second = await admin.post(
        f"/admin/customers/{world.customer_a_id}/contacts",
        json={"name": "Segunda", "whatsapp_e164": "+5511922222222", "is_primary": True},
    )

    assert first.status_code == second.status_code == 201

    listing = await admin.get(f"/admin/customers/{world.customer_a_id}/contacts")
    primaries = [item["name"] for item in listing.json() if item["is_primary"]]
    assert primaries == ["Segunda"]


@pytest.mark.asyncio
async def test_deactivating_a_contact_also_drops_its_primary_mark(world, admin):
    created = await admin.post(
        f"/admin/customers/{world.customer_a_id}/contacts",
        json={"name": "Saindo", "whatsapp_e164": "+5511933333333", "is_primary": True},
    )
    response = await admin.patch(
        f"/admin/customers/{world.customer_a_id}/contacts/{created.json()['contact_id']}",
        json={"active": False},
    )

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert response.json()["is_primary"] is False


@pytest.mark.asyncio
async def test_contact_of_another_portfolio_is_not_reachable(world, representative):
    created = await representative.post(
        f"/admin/customers/{world.customer_a_id}/contacts",
        json={"name": "Minha", "whatsapp_e164": "+5511944444444"},
    )
    contact_id = created.json()["contact_id"]

    # O mesmo contato, pedido através de um cliente de outra carteira.
    response = await representative.patch(
        f"/admin/customers/{world.customer_b_id}/contacts/{contact_id}",
        json={"name": "Invadida"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "customer not found"


@pytest.mark.asyncio
async def test_contact_from_a_different_customer_answers_not_found(world, admin):
    created = await admin.post(
        f"/admin/customers/{world.customer_a_id}/contacts",
        json={"name": "Do A", "whatsapp_e164": "+5511955555555"},
    )
    response = await admin.patch(
        f"/admin/customers/{world.customer_b_id}/contacts/{created.json()['contact_id']}",
        json={"name": "Movido"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "contact not found"


# ------------------------------------------------------------- localidades


@pytest.mark.asyncio
async def test_first_location_of_a_customer_becomes_the_default(world, admin):
    response = await admin.post(
        f"/admin/customers/{world.customer_a_id}/locations",
        json={"label": "Matriz", "state_code": "SP", "is_default": False},
    )

    assert response.status_code == 201
    assert response.json()["is_default"] is True


@pytest.mark.asyncio
async def test_promoting_a_location_demotes_the_previous_default(world, admin):
    await admin.post(
        f"/admin/customers/{world.customer_a_id}/locations",
        json={"label": "Matriz", "state_code": "SP"},
    )
    created = await admin.post(
        f"/admin/customers/{world.customer_a_id}/locations",
        json={"label": "Filial Caxias", "state_code": "RS", "is_default": True},
    )

    assert created.status_code == 201

    listing = await admin.get(f"/admin/customers/{world.customer_a_id}/locations")
    defaults = [item["label"] for item in listing.json() if item["is_default"]]
    assert defaults == ["Filial Caxias"]


@pytest.mark.asyncio
async def test_the_default_location_cannot_be_deactivated_or_demoted(world, admin):
    created = await admin.post(
        f"/admin/customers/{world.customer_a_id}/locations",
        json={"label": "Matriz", "state_code": "SP"},
    )
    location_id = created.json()["location_id"]

    deactivate = await admin.patch(
        f"/admin/customers/{world.customer_a_id}/locations/{location_id}",
        json={"active": False},
    )
    demote = await admin.patch(
        f"/admin/customers/{world.customer_a_id}/locations/{location_id}",
        json={"is_default": False},
    )

    assert deactivate.status_code == demote.status_code == 422
    assert "default" in deactivate.json()["detail"]

    async with world.app.state.session_factory() as session:
        location = await session.scalar(
            select(CustomerLocation).where(CustomerLocation.id == UUID(location_id))
        )
    assert location.is_default is True
    assert location.active is True


@pytest.mark.asyncio
async def test_the_database_itself_refuses_two_active_defaults(world, admin):
    """Garante que o índice parcial existe, e não só a lógica do serviço."""
    await admin.post(
        f"/admin/customers/{world.customer_a_id}/locations",
        json={"label": "Matriz", "state_code": "SP"},
    )

    async with world.app.state.session_factory() as session:
        session.add(
            CustomerLocation(
                id=uuid4(),
                tenant_id=world.tenant_id,
                customer_id=world.customer_a_id,
                label="Segunda padrão",
                state_code="RS",
                is_default=True,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_location_state_is_validated_against_the_federation(world, admin):
    response = await admin.post(
        f"/admin/customers/{world.customer_a_id}/locations",
        json={"label": "Inexistente", "state_code": "ZZ"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_locations_of_another_portfolio_are_not_listed(world, representative):
    response = await representative.get(f"/admin/customers/{world.customer_b_id}/locations")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unknown_location_answers_not_found(world, admin):
    response = await admin.patch(
        f"/admin/customers/{world.customer_a_id}/locations/{uuid4()}",
        json={"label": "X"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "location not found"


# ---------------------------------------------------------------- auditoria


@pytest.mark.asyncio
async def test_registry_changes_are_audited(world, admin):
    created = await admin.post(
        "/admin/customers", json={"legal_name": "Iota Ltda.", "state_code": "BA"}
    )
    customer_id = created.json()["customer_id"]
    await admin.patch(f"/admin/customers/{customer_id}", json={"trade_name": "Iota"})
    await admin.post(
        f"/admin/customers/{customer_id}/contacts",
        json={"name": "Contato", "whatsapp_e164": "+5511966665555"},
    )
    await admin.post(
        f"/admin/customers/{customer_id}/locations",
        json={"label": "Filial", "state_code": "SE"},
    )

    async with world.app.state.session_factory() as session:
        entries = list(await session.scalars(select(AuditLog)))

    recorded = {entry.action for entry in entries}
    assert {
        "CUSTOMER_CREATED",
        "CUSTOMER_UPDATED",
        "CUSTOMER_CONTACT_CREATED",
        "CUSTOMER_LOCATION_CREATED",
    } <= recorded
    assert all(entry.actor_user_id == world.admin_id for entry in entries)


@pytest.mark.asyncio
async def test_registry_requires_authentication(world):
    async with AsyncClient(
        transport=ASGITransport(app=world.app), base_url="http://test"
    ) as anonymous:
        creation = await anonymous.post(
            "/admin/customers", json={"legal_name": "X", "state_code": "SP"}
        )
        contacts = await anonymous.get(f"/admin/customers/{world.customer_a_id}/contacts")

    assert creation.status_code == contacts.status_code == 401


@pytest.mark.asyncio
async def test_seeded_contacts_remain_readable(world, admin):
    """A fixture não cria contatos; a lista vazia é resposta válida, não 404."""
    response = await admin.get(f"/admin/customers/{world.customer_a_id}/contacts")

    assert response.status_code == 200
    assert response.json() == []

    async with world.app.state.session_factory() as session:
        assert list(await session.scalars(select(CustomerContact))) == []
