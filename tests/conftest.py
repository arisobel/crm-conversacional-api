import os

# Onde a suíte roda. Sem `CRM_TEST_DATABASE_URL` nada muda: SQLite em memória,
# um banco novo por teste, na mesma velocidade de sempre. Com a variável
# apontando para um PostgreSQL, a mesma suíte roda contra a engine de produção
# — é assim que a CI descobre um modelo que só era criável no SQLite.
TEST_DATABASE_URL = os.environ.get("CRM_TEST_DATABASE_URL", "sqlite+aiosqlite://")

os.environ.setdefault("CRM_DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("CRM_TENANT_SLUG", "test-tenant")
os.environ.setdefault("CRM_INTERNAL_HMAC_SECRET", "test-secret")

from dataclasses import dataclass  # noqa: E402
from uuid import UUID, uuid4  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from crm_api.core.config import Settings  # noqa: E402
from crm_api.core.passwords import hash_password  # noqa: E402
from crm_api.main import create_app  # noqa: E402
from crm_api.models.base import Base  # noqa: E402
from crm_api.models.catalog import (  # noqa: E402
    CustomerPreferredProduct,
    Product,
    ProductFamily,
)
from crm_api.models.customer import Customer, CustomerLocation, Tenant  # noqa: E402
from crm_api.models.textile import Fiber, ProductComposition  # noqa: E402, F401
from crm_api.models.user import User, UserRole  # noqa: E402

PASSWORD = "SenhaForte12345"
ADMIN_EMAIL = "gestora@teste.com.br"
REPRESENTATIVE_A_EMAIL = "vendedora@teste.com.br"
REPRESENTATIVE_B_EMAIL = "vendedor@teste.com.br"
INACTIVE_EMAIL = "desligado@teste.com.br"


def portal_settings(**overrides) -> Settings:
    values = {
        "database_url": TEST_DATABASE_URL,
        "tenant_slug": "test-tenant",
        "internal_hmac_secret": "test-secret",
        # O cliente de teste fala HTTP; um cookie `Secure` não seria armazenado.
        "session_cookie_secure": False,
    }
    values.update(overrides)
    return Settings(**values)


async def create_schema(engine) -> None:
    """Deixa o banco no estado inicial para o teste que vai começar.

    Em SQLite `://` cada engine abre um banco em memória só dela, e o
    isolamento sai de graça: criar as tabelas basta.

    Em PostgreSQL o banco é um só, compartilhado pelos testes em sequência.
    Escolhi **derrubar e recriar o schema** em vez de reverter transação: os
    testes falam com a aplicação por HTTP, e cada requisição abre a sua própria
    sessão pelo `get_session` — não há uma transação de teste para envolver
    todas elas sem reescrever cada teste. `DROP SCHEMA public CASCADE` é mais
    curto que `drop_all` e mais completo: leva junto os tipos ENUM
    (`interaction_kind`, `customer_intake_status`) e qualquer resto que uma
    versão anterior do modelo tenha deixado.

    Custa uma recriação de esquema por teste, o que é aceitável para um job de
    CI e nunca é pago por quem roda `pytest` sem a variável.
    """
    async with engine.begin() as connection:
        if connection.dialect.name != "sqlite":
            await connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            await connection.exec_driver_sql("CREATE SCHEMA public")
        await connection.run_sync(Base.metadata.create_all)


async def persist(session, objects: list) -> None:
    """Grava um cenário inteiro respeitando a ordem das chaves estrangeiras.

    O `Session.flush` ordena por dependência de `relationship()`, não por
    `ForeignKey`. Como os modelos daqui quase não declaram relationship — o
    acesso é por repositório, não por navegação de objeto —, o flush emite os
    `INSERT` em ordem arbitrária entre tabelas independentes.

    No SQLite isso nunca doeu porque o SQLite não verifica chave estrangeira
    (`PRAGMA foreign_keys` nasce desligado). No PostgreSQL o mesmo cenário
    quebra com `products_tenant_id_fkey`. O produto não tem esse problema: os
    serviços gravam o pai e o filho em passos separados. É artefato de cenário.

    A ordem certa é a que o `create_all` já usa: `metadata.sorted_tables` vem
    topologicamente ordenado pelas FKs. Um flush por tabela, na ordem delas.
    """
    for table in Base.metadata.sorted_tables:
        batch = [obj for obj in objects if inspect(obj).mapper.local_table is table]
        if batch:
            session.add_all(batch)
            await session.flush()


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
    await create_schema(application.state.engine)

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

    # Depois de R2 nenhum cliente existe sem localidade padrão: a migração
    # `0005` fez o backfill e `create_customer` cria a dele junto. O cenário
    # reproduz isso para não testar um estado que produção não tem.
    localidades = [
        CustomerLocation(
            id=uuid4(),
            tenant_id=tenant.id,
            customer_id=cliente.id,
            label="Principal",
            state_code=cliente.state_code,
            is_default=True,
        )
        for cliente in (customer_a, customer_b, customer_unassigned)
    ]

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
        await persist(
            session,
            [
                tenant,
                admin,
                representative_a,
                representative_b,
                inactive,
                customer_a,
                customer_b,
                customer_unassigned,
                *localidades,
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
