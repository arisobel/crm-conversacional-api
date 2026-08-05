"""Carteira de clientes do representante."""

import uuid
from dataclasses import dataclass

from crm_api.models.customer import Customer, CustomerAssignmentHistory
from crm_api.models.user import User
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.portfolio import (
    CustomerFilters,
    CustomerPortfolioRepository,
    PortfolioScope,
)
from crm_api.repositories.users import UserRepository


class CustomerNotInScope(Exception):
    """Cliente inexistente ou fora da carteira do solicitante.

    Um único tipo para os dois casos: a rota traduz para `404` sem revelar qual
    dos dois ocorreu.
    """


class InvalidOwner(Exception):
    """Titular proposto inexistente, inativo ou de outro tenant."""


@dataclass(frozen=True)
class OwnerAssignment:
    customer: Customer
    previous_owner_id: uuid.UUID | None
    changed: bool


class PortfolioService:
    def __init__(
        self,
        *,
        portfolio: CustomerPortfolioRepository,
        users: UserRepository,
        audit: AuditRepository,
    ) -> None:
        self._portfolio = portfolio
        self._users = users
        self._audit = audit

    async def list_customers(
        self,
        scope: PortfolioScope,
        filters: CustomerFilters,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[Customer, User | None]], int]:
        total = await self._portfolio.count_customers(scope, filters)
        rows = await self._portfolio.list_customers(scope, filters, limit=limit, offset=offset)
        return rows, total

    async def get_customer(
        self, scope: PortfolioScope, customer_id: uuid.UUID
    ) -> tuple[Customer, User | None]:
        found = await self._portfolio.get_customer(scope, customer_id)
        if found is None:
            raise CustomerNotInScope
        return found

    async def list_assignment_history(
        self, scope: PortfolioScope, customer_id: uuid.UUID
    ) -> list[tuple[CustomerAssignmentHistory, User | None]]:
        await self.get_customer(scope, customer_id)
        return await self._portfolio.list_assignment_history(scope, customer_id)

    async def assign_owner(
        self,
        scope: PortfolioScope,
        customer_id: uuid.UUID,
        *,
        owner_user_id: uuid.UUID | None,
        actor_user_id: uuid.UUID,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> OwnerAssignment:
        customer, _ = await self.get_customer(scope, customer_id)
        previous_owner_id = customer.owner_user_id

        if owner_user_id is not None:
            owner = await self._users.get_by_id(owner_user_id)
            if owner is None or owner.tenant_id != scope.tenant_id or not owner.active:
                raise InvalidOwner

        if owner_user_id == previous_owner_id:
            # Reatribuir o mesmo titular não é um evento de negócio; gravar
            # histórico aqui encheria a trilha de linhas que não explicam nada.
            return OwnerAssignment(
                customer=customer, previous_owner_id=previous_owner_id, changed=False
            )

        customer.owner_user_id = owner_user_id
        self._portfolio.add_assignment(
            CustomerAssignmentHistory(
                id=uuid.uuid4(),
                tenant_id=scope.tenant_id,
                customer_id=customer.id,
                user_id=owner_user_id,
                assigned_by=actor_user_id,
                reason=reason,
            )
        )
        self._audit.record(
            action="CUSTOMER_OWNER_ASSIGNED" if owner_user_id else "CUSTOMER_OWNER_REMOVED",
            entity="customers",
            tenant_id=scope.tenant_id,
            actor_user_id=actor_user_id,
            entity_id=customer.id,
            before={"owner_user_id": str(previous_owner_id) if previous_owner_id else None},
            after={
                "owner_user_id": str(owner_user_id) if owner_user_id else None,
                "reason": reason,
            },
            request_id=request_id,
        )
        return OwnerAssignment(
            customer=customer, previous_owner_id=previous_owner_id, changed=True
        )
