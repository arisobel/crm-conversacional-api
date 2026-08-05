import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, get_current_user, require_roles
from crm_api.core.database import get_session
from crm_api.models.customer import Customer, CustomerAssignmentHistory
from crm_api.models.user import User, UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.portfolio import (
    CustomerFilters,
    CustomerPortfolioRepository,
    PortfolioScope,
)
from crm_api.repositories.users import UserRepository
from crm_api.schemas.portfolio import (
    AssignmentHistoryEntry,
    CustomerPage,
    CustomerSummary,
    OwnerAssignmentRequest,
    OwnerSummary,
)
from crm_api.services.portfolio import (
    CustomerNotInScope,
    InvalidOwner,
    PortfolioService,
)

router = APIRouter(prefix="/admin", tags=["Portfolio"])

_MANAGEMENT_ROLES = (UserRole.ADMIN, UserRole.MANAGER)


def _build_service(session: AsyncSession) -> PortfolioService:
    return PortfolioService(
        portfolio=CustomerPortfolioRepository(session),
        users=UserRepository(session),
        audit=AuditRepository(session),
    )


def _owner_summary(owner: User | None) -> OwnerSummary | None:
    if owner is None:
        return None
    return OwnerSummary(user_id=owner.id, full_name=owner.full_name, email=owner.email)


def _customer_summary(customer: Customer, owner: User | None) -> CustomerSummary:
    return CustomerSummary(
        customer_id=customer.id,
        legal_name=customer.legal_name,
        trade_name=customer.trade_name,
        document_number=customer.document_number,
        state_code=customer.state_code,
        active=customer.active,
        owner=_owner_summary(owner),
    )


def _not_found() -> HTTPException:
    """`404` também quando o cliente existe fora da carteira.

    Responder `403` confirmaria a existência de uma conta de outro
    representante — é o vazamento que o escopo existe para evitar.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="customer not found")


async def _list(
    service: PortfolioService,
    scope: PortfolioScope,
    *,
    state_code: str | None,
    preferred_product_id: uuid.UUID | None,
    active: bool | None,
    assigned: bool | None,
    search: str | None,
    limit: int,
    offset: int,
) -> CustomerPage:
    filters = CustomerFilters(
        state_code=state_code.upper() if state_code else None,
        preferred_product_id=preferred_product_id,
        active=active,
        assigned=assigned,
        search=search,
    )
    rows, total = await service.list_customers(scope, filters, limit=limit, offset=offset)
    return CustomerPage(
        items=[_customer_summary(customer, owner) for customer, owner in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/customers", response_model=CustomerPage)
async def list_customers(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    state_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    preferred_product_id: Annotated[uuid.UUID | None, Query()] = None,
    active: Annotated[bool | None, Query()] = None,
    assigned: Annotated[bool | None, Query()] = None,
    search: Annotated[str | None, Query(min_length=2, max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerPage:
    """Lista clientes do tenant, já reduzidos ao que o papel permite ver.

    `ADMIN` e `MANAGER` enxergam todo o tenant, inclusive clientes sem titular;
    `REPRESENTATIVE` enxerga apenas a própria carteira.
    """
    scope = PortfolioScope.for_user(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
    )
    return await _list(
        _build_service(session),
        scope,
        state_code=state_code,
        preferred_product_id=preferred_product_id,
        active=active,
        assigned=assigned,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/me/customers", response_model=CustomerPage)
async def list_my_customers(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    state_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    preferred_product_id: Annotated[uuid.UUID | None, Query()] = None,
    active: Annotated[bool | None, Query()] = None,
    search: Annotated[str | None, Query(min_length=2, max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CustomerPage:
    """A carteira de quem está logado, qualquer que seja o papel."""
    scope = PortfolioScope.for_user(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
        only_own=True,
    )
    return await _list(
        _build_service(session),
        scope,
        state_code=state_code,
        preferred_product_id=preferred_product_id,
        active=active,
        assigned=True,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerSummary,
    responses={404: {"description": "Not found or outside the portfolio"}},
)
async def get_customer(
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CustomerSummary:
    scope = PortfolioScope.for_user(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
    )
    try:
        customer, owner = await _build_service(session).get_customer(scope, customer_id)
    except CustomerNotInScope as error:
        raise _not_found() from error
    return _customer_summary(customer, owner)


@router.put(
    "/customers/{customer_id}/owner",
    response_model=CustomerSummary,
    responses={
        403: {"description": "Insufficient role"},
        404: {"description": "Not found"},
        422: {"description": "Invalid owner"},
    },
)
async def assign_customer_owner(
    customer_id: uuid.UUID,
    payload: OwnerAssignmentRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(require_roles(*_MANAGEMENT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CustomerSummary:
    """Designa, transfere ou remove o titular da conta.

    Reatribuir o titular já vigente é um no-op e não gera linha de histórico.
    """
    scope = PortfolioScope.for_user(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
    )
    service = _build_service(session)
    try:
        assignment = await service.assign_owner(
            scope,
            customer_id,
            owner_user_id=payload.owner_user_id,
            actor_user_id=current_user.user_id,
            reason=payload.reason,
            request_id=request.headers.get("x-request-id"),
        )
    except CustomerNotInScope as error:
        raise _not_found() from error
    except InvalidOwner as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="owner must be an active user of this tenant",
        ) from error

    await session.commit()
    customer, owner = await service.get_customer(scope, assignment.customer.id)
    return _customer_summary(customer, owner)


@router.get(
    "/customers/{customer_id}/assignment-history",
    response_model=list[AssignmentHistoryEntry],
    responses={403: {"description": "Insufficient role"}, 404: {"description": "Not found"}},
)
async def list_assignment_history(
    customer_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_roles(*_MANAGEMENT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AssignmentHistoryEntry]:
    scope = PortfolioScope.for_user(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
    )
    try:
        rows = await _build_service(session).list_assignment_history(scope, customer_id)
    except CustomerNotInScope as error:
        raise _not_found() from error

    return [_history_entry(entry, owner) for entry, owner in rows]


def _history_entry(
    entry: CustomerAssignmentHistory, owner: User | None
) -> AssignmentHistoryEntry:
    return AssignmentHistoryEntry(
        assigned_at=entry.assigned_at,
        assigned_by=entry.assigned_by,
        reason=entry.reason,
        owner=_owner_summary(owner),
    )
