from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.repositories.customers import CustomerRepository
from crm_api.repositories.price_lists import PriceListRepository
from crm_api.schemas.price_lists import CurrentPriceListResponse
from crm_api.services.customers import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.services.price_lists import CurrentPriceListService

router = APIRouter(tags=["Price Lists"])


@router.get(
    "/price-lists/current/by-whatsapp/{phone}",
    response_model=CurrentPriceListResponse,
    responses={401: {"description": "Unauthorized"}, 404: {"description": "Not found"}},
)
async def get_current_price_list_by_whatsapp(
    phone: str,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentPriceListResponse:
    try:
        normalized_phone = normalize_whatsapp_e164(phone)
    except InvalidWhatsappNumber as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    service = CurrentPriceListService(
        CustomerRepository(session), PriceListRepository(session)
    )
    current_price_list = await service.find_by_whatsapp(tenant_slug, normalized_phone)
    if current_price_list is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="current price list not found for customer contact",
        )
    return current_price_list
