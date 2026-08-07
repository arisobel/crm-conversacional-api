from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.customers import CustomerRepository
from crm_api.repositories.icms import IcmsRuleRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.repositories.price_lists import PriceListRepository
from crm_api.schemas.price_lists import CurrentPriceListResponse
from crm_api.services.customer_price_list import (
    CustomerPriceListService,
    LocationUnavailable,
    PricesUnavailable,
)
from crm_api.services.customers import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.services.icms import (
    AmbiguousIcmsRule,
    IcmsResolver,
    IcmsRuleNotFound,
    InvalidTaxRate,
    OriginNotConfigured,
)
from crm_api.services.portfolio import CustomerNotInScope
from crm_api.services.price_lists import CurrentPriceListService

router = APIRouter(tags=["Price Lists"])

_NOT_FOUND_DETAIL = "current price list not found for customer contact"


def _build_service(request: Request, session: AsyncSession) -> CurrentPriceListService:
    """Monta o serviço com a conversão de ICMS pendurada.

    O serviço só usa a conversão quando `whatsapp_icms_enabled` está ligado; a
    dependência é sempre construída porque montá-la não custa consulta alguma.
    """
    settings = request.app.state.settings
    return CurrentPriceListService(
        CustomerRepository(session),
        PriceListRepository(session),
        PriceEntryRepository(session),
        resolved_service=CustomerPriceListService(
            portfolio=CustomerPortfolioRepository(session),
            admin=CustomerAdminRepository(session),
            entries=PriceEntryRepository(session),
            resolver=IcmsResolver(IcmsRuleRepository(session)),
            settings=settings,
        ),
        settings=settings,
    )


@contextmanager
def _translated_pricing_errors() -> Iterator[None]:
    """Traduz as falhas da conversão para códigos que o Gateway distingue.

    Só alcança o regime convertido: com o interruptor desligado nenhuma dessas
    exceções chega a ser levantada, e a rota responde `404` para toda ausência,
    exatamente como o Gateway em produção já espera.
    """
    try:
        yield
    except CustomerNotInScope as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from error
    except (IcmsRuleNotFound, AmbiguousIcmsRule) as error:
        # Conflito, não "não encontrado": a tabela existe, o que falta é a regra
        # fiscal que permite exibi-la para esta praça.
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


def _normalized_phone(phone: str) -> str:
    try:
        return normalize_whatsapp_e164(phone)
    except InvalidWhatsappNumber as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.get(
    "/price-lists/current/by-whatsapp/{phone}",
    response_model=CurrentPriceListResponse,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        409: {"description": "Missing or ambiguous ICMS rule"},
        422: {"description": "Missing location, origin or published competence"},
    },
)
async def get_current_price_list_by_whatsapp(
    phone: str,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentPriceListResponse:
    service = _build_service(request, session)
    with _translated_pricing_errors():
        current_price_list = await service.find_by_whatsapp(
            tenant_slug, _normalized_phone(phone)
        )
    if current_price_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    return current_price_list


@router.get(
    "/price-lists/current/by-whatsapp/{phone}/items",
    response_model=CurrentPriceListResponse,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        409: {"description": "Missing or ambiguous ICMS rule"},
        422: {"description": "Missing location, origin or published competence"},
    },
)
async def search_current_price_list_items_by_whatsapp(
    phone: str,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
    query: Annotated[str, Query(min_length=2, max_length=120)],
) -> CurrentPriceListResponse:
    service = _build_service(request, session)
    with _translated_pricing_errors():
        current_price_list = await service.search_items_by_whatsapp(
            tenant_slug, _normalized_phone(phone), query
        )
    if current_price_list is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    return current_price_list
