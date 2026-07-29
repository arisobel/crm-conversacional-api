import re
import unicodedata
from datetime import UTC, datetime

from crm_api.models.pricing import AvailabilityStatus
from crm_api.repositories.customers import CustomerRepository
from crm_api.repositories.price_lists import PriceListRepository
from crm_api.schemas.customers import CustomerContactResponse
from crm_api.schemas.price_lists import (
    CurrentPriceListItemResponse,
    CurrentPriceListResponse,
    PriceListSummaryResponse,
)

_NO_CURRENT_PRICE = {
    AvailabilityStatus.OUT_OF_STOCK,
    AvailabilityStatus.SUSPENDED,
    AvailabilityStatus.CONSULT,
}
_SEARCH_SEPARATOR = re.compile(r"[^a-z0-9]+")


def _search_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return [token for token in _SEARCH_SEPARATOR.split(ascii_value.casefold()) if token]


def _matches_search_terms(item: CurrentPriceListItemResponse, terms: list[str]) -> bool:
    searchable_value = " ".join(
        part
        for part in (item.sku, item.display_name, item.specification, item.family_name)
        if part
    )
    searchable_tokens = set(_search_tokens(searchable_value))
    return all(term in searchable_tokens for term in terms)


class CurrentPriceListService:
    def __init__(
        self, customer_repository: CustomerRepository, price_list_repository: PriceListRepository
    ):
        self._customer_repository = customer_repository
        self._price_list_repository = price_list_repository

    async def find_by_whatsapp(
        self, tenant_slug: str, phone: str, *, at: datetime | None = None
    ) -> CurrentPriceListResponse | None:
        contact_and_customer = await self._customer_repository.get_active_by_whatsapp(
            tenant_slug, phone
        )
        if contact_and_customer is None:
            return None
        contact, customer = contact_and_customer
        price_list = await self._price_list_repository.get_current(
            customer.tenant_id, at or datetime.now(UTC)
        )
        if price_list is None:
            return None

        item_rows = await self._price_list_repository.list_items(price_list.id)
        return CurrentPriceListResponse(
            customer=CustomerContactResponse(
                customer_id=customer.id,
                customer_name=customer.legal_name,
                state_code=customer.state_code,
                contact_id=contact.id,
                contact_name=contact.name,
                whatsapp_e164=contact.whatsapp_e164,
            ),
            price_list=PriceListSummaryResponse.model_validate(price_list),
            items=[
                CurrentPriceListItemResponse(
                    product_id=product.id,
                    family_name=family.name,
                    sku=product.sku,
                    display_name=product.commercial_name,
                    specification=product.specification,
                    unit=product.unit,
                    availability=item.availability.value,
                    base_price=None if item.availability in _NO_CURRENT_PRICE else item.base_price,
                    expected_arrival_date=item.expected_arrival_date,
                    arrival_note=item.arrival_note,
                    notes=item.notes,
                )
                for item, product, family in item_rows
            ],
        )

    async def search_items_by_whatsapp(
        self, tenant_slug: str, phone: str, query: str, *, at: datetime | None = None
    ) -> CurrentPriceListResponse | None:
        current_price_list = await self.find_by_whatsapp(tenant_slug, phone, at=at)
        if current_price_list is None:
            return None

        search_terms = _search_tokens(query)
        if not search_terms:
            return current_price_list.model_copy(update={"items": []})
        matching_items = [
            item
            for item in current_price_list.items
            if _matches_search_terms(item, search_terms)
        ]
        return current_price_list.model_copy(update={"items": matching_items})
