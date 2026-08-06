from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ResolvedItemResponse(BaseModel):
    product_id: UUID
    sku: str
    family_name: str
    display_name: str
    specification: str | None
    unit: str
    availability: str
    base_price: Decimal | None
    final_price: Decimal | None
    tax_rate: Decimal | None
    expected_arrival_date: date | None
    arrival_note: str | None
    notes: str | None
    trace: dict | None = Field(
        default=None,
        description="Regra aplicada, alíquotas e valores intermediários do cálculo.",
    )


class ResolvedPriceListResponse(BaseModel):
    customer_id: UUID
    customer_name: str
    location_id: UUID
    location_label: str
    origin_state: str
    destination_state: str
    reference_month: date
    currency: str
    items: list[ResolvedItemResponse]


class IcmsRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: UUID
    origin_state: str
    destination_state: str
    product_id: UUID | None
    family_id: UUID | None
    customer_id: UUID | None
    tax_rate: Decimal
    valid_from: date
    valid_until: date | None
    priority: int
    active: bool


class CreateIcmsRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin_state: str = Field(min_length=2, max_length=2)
    destination_state: str = Field(min_length=2, max_length=2)
    tax_rate: Decimal = Field(ge=0, le=100)
    valid_from: date
    valid_until: date | None = None
    product_id: UUID | None = None
    family_id: UUID | None = None
    customer_id: UUID | None = None
    priority: int = 100
