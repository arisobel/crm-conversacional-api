import os

os.environ.setdefault("CRM_DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("CRM_TENANT_SLUG", "test-tenant")
os.environ.setdefault("CRM_INTERNAL_HMAC_SECRET", "test-secret")

from dataclasses import dataclass  # noqa: E402
from uuid import UUID, uuid4  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from crm_api.core.config import Settings  # noqa: E402
from crm_api.core.passwords import hash_password  # noqa: E402
from crm_api.main import create_app  # noqa: E402
from crm_api.models.base import Base  # noqa: E402
from crm_api.models.catalog import (  # noqa: E402
    CustomerPreferredProduct,
    Product,
    ProductFamily,
)
from crm_api.models.customer import Customer, Tenant  # noqa: E402
from crm_api.models.user import User, UserRole  # noqa: E402

PASSWORD = "SenhaForte12345"
ADMIN_EMAIL = "gestora@teste.com.br"
REPRESENTATIVE_A_EMAIL = "vendedora@teste.com.br"
REPRESENTATIVE_B_EMAIL = "vendedor@teste.com.br"
INACTIVE_EMAIL = "desligado@teste.com.br"


def portal_settings(**overrides) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite://",
        "tenant_slug": "test-tenant",
        "internal_hmac_secret": "test-secret",
        # O cliente de teste fala HTTP; um cookie `Secure` não seria armazenado.
        "session_cookie_secure": False,
    }
    values.update(overrides)
    return Settings(**values)


@dataclass(frozen=True)
class PortalWorld:
    """Cenário mínimo para exercitar escopo de carteira e papéis."""

    app: FastAPI
    tenant_id: UUID
    admin_id: UUID
    representative_a_id: UUID
    representative_b_id: UUID
    inactive_user_id: UUID
    customer_a_id: UUID
    customer_b_id: UUID
    customer_unassigned_id: UUID
    product_id: UUID


async def build_portal_world(**setting_overrides) -> PortalWorld:
    application = create_app(portal_settings(**setting_overrides))
    async with application.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    tenant = Tenant(id=uuid4(), name="Tenant de teste", slug="test-tenant")
    password_hash = hash_password(PASSWORD)

    def _user(email: str, name: str, role: UserRole, *, active: bool = True) -> User:
        return User(
            id=uuid4(),
            tenant_id=tenant.id,
            full_name=name,
            email=email,
            password_hash=password_hash,
            role=role,
            active=active,
        )

    admin = _user(ADMIN_EMAIL, "Gestora Exemplo", UserRole.ADMIN)
    representative_a = _user(REPRESENTATIVE_A_EMAIL, "Vendedora A", UserRole.REPRESENTATIVE)
    representative_b = _user(REPRESENTATIVE_B_EMAIL, "Vendedor B", UserRole.REPRESENTATIVE)
    inactive = _user(
        INACTIVE_EMAIL, "Desligado Exemplo", UserRole.REPRESENTATIVE, active=False
    )

    customer_a = Customer(
        id=uuid4(),
        tenant_id=tenant.id,
        legal_name="Alfa Tecelagem Ltda.",
        trade_name="Alfa",
        document_number="11111111000111",
        state_code="SP",
        owner_user_id=representative_a.id,
    )
    customer_b = Customer(
        id=uuid4(),
        tenant_id=tenant.id,
        legal_name="Beta Malharia Ltda.",
        state_code="RS",
        owner_user_id=representative_b.id,
    )
    customer_unassigned = Customer(
        id=uuid4(),
        tenant_id=tenant.id,
        legal_name="Gama Confecções Ltda.",
        state_code="SP",
    )

    family = ProductFamily(id=uuid4(), tenant_id=tenant.id, name="Texturizado")
    product = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        family_id=family.id,
        sku="TEX-75-36-CRU",
        commercial_name="75/36 trama cru",
    )
    preference = CustomerPreferredProduct(
        id=uuid4(),
        tenant_id=tenant.id,
        customer_id=customer_a.id,
        product_id=product.id,
    )

    async with application.state.session_factory() as session:
        session.add_all(
            [
                tenant,
                admin,
                representative_a,
                representative_b,
                inactive,
                customer_a,
                customer_b,
                customer_unassigned,
                family,
                product,
                preference,
            ]
        )
        await session.commit()

    return PortalWorld(
        app=application,
        tenant_id=tenant.id,
        admin_id=admin.id,
        representative_a_id=representative_a.id,
        representative_b_id=representative_b.id,
        inactive_user_id=inactive.id,
        customer_a_id=customer_a.id,
        customer_b_id=customer_b.id,
        customer_unassigned_id=customer_unassigned.id,
        product_id=product.id,
    )


async def login(client, *, email: str, password: str = PASSWORD):
    return await client.post("/admin/auth/login", json={"email": email, "password": password})
