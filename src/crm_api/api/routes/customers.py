from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.repositories.customers import CustomerRepository
from crm_api.schemas.customers import CustomerContactResponse
from crm_api.services.customers import (
    CustomerService,
    InvalidWhatsappNumber,
    normalize_whatsapp_e164,
)

router = APIRouter(tags=["Customers"])


@router.get(
    "/customers/by-whatsapp/{phone}",
    response_model=CustomerContactResponse,
    responses={401: {"description": "Unauthorized"}, 404: {"description": "Not found"}},
)
async def find_customer_by_whatsapp(
    phone: str,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CustomerContactResponse:
    try:
        normalized_phone = normalize_whatsapp_e164(phone)
    except InvalidWhatsappNumber as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    service = CustomerService(CustomerRepository(session))
    customer_contact = await service.find_active_by_whatsapp(tenant_slug, normalized_phone)
    if customer_contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="customer contact not found",
        )
    return customer_contact
