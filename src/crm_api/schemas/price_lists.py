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
    specification: str | None
    unit: str
    availability: str
    base_price: Decimal | None
    # Preço convertido para a UF onde o cliente recebe, e a alíquota aplicada.
    # Nulos quando a conversão está desligada — `base_price` permanece sendo o
    # valor a exibir nesse caso. Campos aditivos: um Gateway anterior a esta
    # versão continua lendo `base_price` e funcionando.
    final_price: Decimal | None = None
    tax_rate: Decimal | None = None
    expected_arrival_date: date | None
    arrival_note: str | None
    notes: str | None


class CurrentPriceListResponse(BaseModel):
    customer: CustomerContactResponse
    price_list: PriceListSummaryResponse
    # Par de UFs da conversão. Nulos quando ela está desligada; presentes, dizem
    # ao Gateway que o preço exibido já é o da praça do cliente.
    origin_state: str | None = None
    destination_state: str | None = None
    items: list[CurrentPriceListItemResponse]
