"""Lista de preços resolvida por cliente e matriz de ICMS."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, get_current_user, require_roles
from crm_api.api.scoping import scope_for
from crm_api.core.database import get_session
from crm_api.core.states import InvalidStateCode, normalize_state_code
from crm_api.models.tax import IcmsRule
from crm_api.models.user import UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.icms import IcmsRuleRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.repositories.users import UserRepository
from crm_api.schemas.pricing_resolved import (
    CreateIcmsRuleRequest,
    IcmsRuleResponse,
    ResolvedItemResponse,
    ResolvedPriceListResponse,
)
from crm_api.services.customer_price_list import (
    CustomerPriceListService,
    LocationUnavailable,
    PricesUnavailable,
)
from crm_api.services.icms import (
    AmbiguousIcmsRule,
    IcmsResolver,
    IcmsRuleNotFound,
    InvalidTaxRate,
    OriginNotConfigured,
)
from crm_api.services.portfolio import CustomerNotInScope

router = APIRouter(prefix="/admin", tags=["Pricing"])


def _price_list_service(request: Request, session: AsyncSession) -> CustomerPriceListService:
    return CustomerPriceListService(
        portfolio=CustomerPortfolioRepository(session),
        admin=CustomerAdminRepository(session),
        entries=PriceEntryRepository(session),
        resolver=IcmsResolver(IcmsRuleRepository(session)),
        settings=request.app.state.settings,
    )


@router.get(
    "/customers/{customer_id}/price-list",
    response_model=ResolvedPriceListResponse,
    responses={
        404: {"description": "Customer not found or outside the portfolio"},
        409: {"description": "Ambiguous or missing ICMS rule"},
        422: {"description": "Missing location, origin or published competence"},
    },
)
async def resolved_price_list(
    customer_id: uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    reference_month: Annotated[date | None, Query()] = None,
) -> ResolvedPriceListResponse:
    """Produtos preferidos do cliente, com o preço convertido para a UF dele.

    Regra de ICMS ausente ou ambígua **interrompe a lista inteira**: entregar
    uma tabela silenciosamente incompleta faria o representante cotar em cima
    dela.
    """
    tenant = await UserRepository(session).get_tenant(request.app.state.settings.tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    try:
        resolvida = await _price_list_service(request, session).resolve(
            scope_for(current_user),
            customer_id,
            origin_state=tenant.origin_state_code,
            location_id=location_id,
            month=reference_month.replace(day=1) if reference_month else None,
        )
    except CustomerNotInScope as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="customer not found"
        ) from error
    except (AmbiguousIcmsRule, IcmsRuleNotFound) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (
        LocationUnavailable,
        PricesUnavailable,
        OriginNotConfigured,
        InvalidTaxRate,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    return ResolvedPriceListResponse(
        customer_id=resolvida.customer.id,
        customer_name=resolvida.customer.legal_name,
        location_id=resolvida.location.id,
        location_label=resolvida.location.label,
        origin_state=resolvida.origin_state,
        destination_state=resolvida.location.state_code,
        reference_month=resolvida.reference_month,
        currency=resolvida.currency,
        items=[ResolvedItemResponse(**vars(item)) for item in resolvida.items],
    )


@router.get(
    "/icms-rules",
    response_model=list[IcmsRuleResponse],
    responses={403: {"description": "Insufficient role"}},
)
async def list_icms_rules(
    current_user: Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_session)],
    active: Annotated[bool | None, Query()] = None,
) -> list[IcmsRuleResponse]:
    regras = await IcmsRuleRepository(session).list_rules(
        current_user.tenant_id, active=active
    )
    return [_response(regra) for regra in regras]


@router.post(
    "/icms-rules",
    response_model=IcmsRuleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Insufficient role"},
        422: {"description": "Invalid state code or conflicting specialization"},
    },
)
async def create_icms_rule(
    payload: CreateIcmsRuleRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IcmsRuleResponse:
    if payload.product_id is not None and payload.family_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="product_id and family_id are mutually exclusive",
        )
    try:
        origem = normalize_state_code(payload.origin_state)
        destino = normalize_state_code(payload.destination_state)
    except InvalidStateCode as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    regra = IcmsRule(
        id=uuid.uuid4(),
        tenant_id=current_user.tenant_id,
        origin_state=origem,
        destination_state=destino,
        product_id=payload.product_id,
        family_id=payload.family_id,
        customer_id=payload.customer_id,
        tax_rate=payload.tax_rate,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        priority=payload.priority,
    )
    IcmsRuleRepository(session).add(regra)
    AuditRepository(session).record(
        action="ICMS_RULE_CREATED",
        entity="icms_rules",
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.user_id,
        entity_id=regra.id,
        after={
            "origin_state": origem,
            "destination_state": destino,
            "tax_rate": str(payload.tax_rate),
            "valid_from": payload.valid_from.isoformat(),
        },
        request_id=request.headers.get("x-request-id"),
    )
    await session.commit()
    return _response(regra)


def _response(regra: IcmsRule) -> IcmsRuleResponse:
    return IcmsRuleResponse(
        rule_id=regra.id,
        origin_state=regra.origin_state,
        destination_state=regra.destination_state,
        product_id=regra.product_id,
        family_id=regra.family_id,
        customer_id=regra.customer_id,
        tax_rate=regra.tax_rate,
        valid_from=regra.valid_from,
        valid_until=regra.valid_until,
        priority=regra.priority,
        active=regra.active,
    )
