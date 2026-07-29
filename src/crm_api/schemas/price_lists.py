from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from crm_api.schemas.customers import CustomerContactResponse


class PriceListSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    reference_month: date
    valid_from: datetime
    valid_until: datetime | None
    currency: str


class CurrentPriceListItemResponse(BaseModel):
    product_id: UUID
    family_name: str
    sku: str
    display_name: str
    unit: str
    availability: str
    base_price: Decimal | None
    expected_arrival_date: date | None
    arrival_note: str | None
    notes: str | None


class CurrentPriceListResponse(BaseModel):
    customer: CustomerContactResponse
    price_list: PriceListSummaryResponse
    items: list[CurrentPriceListItemResponse]
