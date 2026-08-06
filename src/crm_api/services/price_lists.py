import re
import unicodedata
import uuid
from calendar import monthrange
from datetime import UTC, date, datetime, time

from crm_api.models.pricing import AvailabilityStatus, PriceEntry
from crm_api.repositories.customers import CustomerRepository
from crm_api.repositories.price_entries import PriceEntryRepository
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
_MESES_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


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
    """Tabela vigente para um contato, lida de `price_entries`.

    Desde a `0006` a fonte de verdade é a competência, não mais o cabeçalho da
    tabela. O bloco `price_list` da resposta é preservado — o Gateway já o
    consome em produção — e passa a descrever **o lote que publicou** os preços
    vigentes daquele mês.
    """

    def __init__(
        self,
        customer_repository: CustomerRepository,
        price_list_repository: PriceListRepository,
        price_entry_repository: PriceEntryRepository,
    ):
        self._customer_repository = customer_repository
        self._price_list_repository = price_list_repository
        self._price_entry_repository = price_entry_repository

    async def _summary(
        self, tenant_id: uuid.UUID, month: date, entries: list[PriceEntry]
    ) -> PriceListSummaryResponse:
        lote = None
        publicadas = [entry for entry in entries if entry.source_batch_id is not None]
        if publicadas:
            mais_recente = max(publicadas, key=lambda entry: entry.published_at)
            lote = await self._price_list_repository.get_by_id(
                tenant_id, mais_recente.source_batch_id
            )
        if lote is not None:
            return PriceListSummaryResponse.model_validate(lote)

        # Preço gravado sem lote de origem. Não deveria acontecer pelo fluxo
        # normal; o identificador derivado mantém a resposta estável em vez de
        # quebrar o contrato do Gateway por um dado incompleto.
        ultimo_dia = monthrange(month.year, month.month)[1]
        return PriceListSummaryResponse(
            id=uuid.uuid5(_MESES_NAMESPACE, f"{tenant_id}:{month.isoformat()}"),
            name=f"Tabela {month.month:02d}/{month.year}",
            reference_month=month,
            valid_from=datetime.combine(month, time.min, tzinfo=UTC),
            valid_until=datetime.combine(
                month.replace(day=ultimo_dia), time.max, tzinfo=UTC
            ),
            currency="BRL",
        )

    async def find_by_whatsapp(
        self, tenant_slug: str, phone: str, *, at: datetime | None = None
    ) -> CurrentPriceListResponse | None:
        contact_and_customer = await self._customer_repository.get_active_by_whatsapp(
            tenant_slug, phone
        )
        if contact_and_customer is None:
            return None
        contact, customer = contact_and_customer

        momento = at or datetime.now(UTC)
        entries_repository = self._price_entry_repository
        month = await entries_repository.latest_month(customer.tenant_id, at=momento.date())
        if month is None:
            return None

        item_rows = await entries_repository.list_items(customer.tenant_id, month)
        summary = await self._summary(
            customer.tenant_id, month, [entry for entry, _, _ in item_rows]
        )
        return CurrentPriceListResponse(
            customer=CustomerContactResponse(
                customer_id=customer.id,
                customer_name=customer.legal_name,
                state_code=customer.state_code,
                contact_id=contact.id,
                contact_name=contact.name,
                whatsapp_e164=contact.whatsapp_e164,
            ),
            price_list=summary,
            items=[
                CurrentPriceListItemResponse(
                    product_id=product.id,
                    family_name=family.name,
                    sku=product.sku,
                    display_name=product.commercial_name,
                    specification=product.specification,
                    unit=product.unit,
                    availability=entry.availability.value,
                    base_price=(
                        None if entry.availability in _NO_CURRENT_PRICE else entry.base_price
                    ),
                    expected_arrival_date=entry.expected_arrival_date,
                    arrival_note=entry.arrival_note,
                    notes=entry.notes,
                )
                for entry, product, family in item_rows
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
