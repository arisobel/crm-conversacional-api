"""Leitura da carteira de clientes, sempre com escopo obrigatório.

O escopo é um argumento posicional exigido por todos os métodos: não existe
consulta de cliente sem ele. A alternativa — filtrar na camada de rota — deixa a
porta aberta para uma rota nova esquecer o filtro e expor a carteira alheia.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import CustomerPreferredProduct
from crm_api.models.customer import Customer, CustomerAssignmentHistory
from crm_api.models.user import User, UserRole


@dataclass(frozen=True)
class PortfolioScope:
    """Limite de linhas que o solicitante pode enxergar.

    `owner_user_id` nulo significa "todo o tenant" e só é produzido para
    `ADMIN` e `MANAGER`.
    """

    tenant_id: uuid.UUID
    owner_user_id: uuid.UUID | None

    @classmethod
    def for_user(
        cls,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        role: UserRole,
        only_own: bool = False,
    ) -> "PortfolioScope":
        restricted = only_own or role is UserRole.REPRESENTATIVE
        return cls(tenant_id=tenant_id, owner_user_id=user_id if restricted else None)


@dataclass(frozen=True)
class CustomerFilters:
    state_code: str | None = None
    preferred_product_id: uuid.UUID | None = None
    active: bool | None = None
    assigned: bool | None = None
    search: str | None = None


class CustomerPortfolioRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def _scoped(self, scope: PortfolioScope) -> Select[tuple[Customer, User | None]]:
        statement = (
            select(Customer, User)
            .outerjoin(User, User.id == Customer.owner_user_id)
            .where(Customer.tenant_id == scope.tenant_id)
        )
        if scope.owner_user_id is not None:
            statement = statement.where(Customer.owner_user_id == scope.owner_user_id)
        return statement

    def _filtered(
        self, scope: PortfolioScope, filters: CustomerFilters
    ) -> Select[tuple[Customer, User | None]]:
        statement = self._scoped(scope)
        if filters.state_code is not None:
            statement = statement.where(Customer.state_code == filters.state_code)
        if filters.active is not None:
            statement = statement.where(Customer.active.is_(filters.active))
        if filters.assigned is True:
            statement = statement.where(Customer.owner_user_id.is_not(None))
        elif filters.assigned is False:
            statement = statement.where(Customer.owner_user_id.is_(None))
        if filters.preferred_product_id is not None:
            statement = statement.where(
                select(CustomerPreferredProduct.id)
                .where(
                    CustomerPreferredProduct.customer_id == Customer.id,
                    CustomerPreferredProduct.product_id == filters.preferred_product_id,
                    CustomerPreferredProduct.active.is_(True),
                )
                .exists()
            )
        if filters.search:
            term = f"%{filters.search.strip()}%"
            statement = statement.where(
                or_(
                    Customer.legal_name.ilike(term),
                    Customer.trade_name.ilike(term),
                    Customer.document_number.ilike(term),
                )
            )
        return statement

    async def count_customers(self, scope: PortfolioScope, filters: CustomerFilters) -> int:
        statement = self._filtered(scope, filters).with_only_columns(func.count(Customer.id))
        return await self._session.scalar(statement.order_by(None)) or 0

    async def list_customers(
        self,
        scope: PortfolioScope,
        filters: CustomerFilters,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[Customer, User | None]]:
        statement = (
            self._filtered(scope, filters)
            .order_by(Customer.legal_name, Customer.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(statement)
        return list(result.tuples())

    async def get_customer(
        self, scope: PortfolioScope, customer_id: uuid.UUID
    ) -> tuple[Customer, User | None] | None:
        """Devolve `None` quando o cliente não existe **ou** está fora do escopo.

        Os dois casos são indistinguíveis de propósito: responder `403` para o
        segundo confirmaria a existência de uma conta de outra carteira.
        """
        result = await self._session.execute(
            self._scoped(scope).where(Customer.id == customer_id)
        )
        return result.tuples().one_or_none()

    async def list_assignment_history(
        self, scope: PortfolioScope, customer_id: uuid.UUID
    ) -> list[tuple[CustomerAssignmentHistory, User | None]]:
        result = await self._session.execute(
            select(CustomerAssignmentHistory, User)
            .outerjoin(User, User.id == CustomerAssignmentHistory.user_id)
            .where(
                CustomerAssignmentHistory.customer_id == customer_id,
                CustomerAssignmentHistory.tenant_id == scope.tenant_id,
            )
            .order_by(CustomerAssignmentHistory.assigned_at.desc())
        )
        return list(result.tuples())

    def add_assignment(self, entry: CustomerAssignmentHistory) -> None:
        self._session.add(entry)
