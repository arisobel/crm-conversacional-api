"""Lista de preços de um cliente: produtos preferidos, na UF onde ele recebe.

É a junção das três etapas: preço por competência (R3), localidade (R2) e
alíquota por par de UFs (R4).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from crm_api.core.config import Settings
from crm_api.models.customer import Customer, CustomerLocation
from crm_api.models.pricing import AvailabilityStatus
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository, PortfolioScope
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.services.icms import ConversionMode, IcmsResolver, convert_price
from crm_api.services.portfolio import CustomerNotInScope

# Disponibilidades em que não existe preço comercial atual. Converter ICMS
# sobre elas seria calcular imposto sobre um valor que não será exibido.
_SEM_PRECO = {
    AvailabilityStatus.OUT_OF_STOCK,
    AvailabilityStatus.SUSPENDED,
    AvailabilityStatus.CONSULT,
}


class LocationUnavailable(Exception):
    """Cliente sem localidade utilizável para determinar a UF de destino."""


class PricesUnavailable(Exception):
    """Não há competência publicada aplicável."""


@dataclass(frozen=True)
class ResolvedItem:
    product_id: uuid.UUID
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
    trace: dict | None


@dataclass(frozen=True)
class ResolvedPriceList:
    customer: Customer
    location: CustomerLocation
    reference_month: date
    origin_state: str
    currency: str
    items: list[ResolvedItem]


class CustomerPriceListService:
    def __init__(
        self,
        *,
        portfolio: CustomerPortfolioRepository,
        admin: CustomerAdminRepository,
        entries: PriceEntryRepository,
        resolver: IcmsResolver,
        settings: Settings,
    ) -> None:
        self._portfolio = portfolio
        self._admin = admin
        self._entries = entries
        self._resolver = resolver
        self._settings = settings

    async def resolve(
        self,
        scope: PortfolioScope,
        customer_id: uuid.UUID,
        *,
        origin_state: str | None,
        location_id: uuid.UUID | None = None,
        month: date | None = None,
        at: date | None = None,
    ) -> ResolvedPriceList:
        encontrado = await self._portfolio.get_customer(scope, customer_id)
        if encontrado is None:
            raise CustomerNotInScope
        cliente, _ = encontrado

        localidade = (
            await self._admin.get_location(customer_id, location_id)
            if location_id
            else await self._admin.get_default_location(customer_id)
        )
        if localidade is None or not localidade.active:
            raise LocationUnavailable(
                "cliente sem localidade padrão ativa; cadastre uma para determinar a UF"
            )

        referencia = at or date.today()
        competencia = month or await self._entries.latest_month(
            scope.tenant_id, at=referencia
        )
        if competencia is None:
            raise PricesUnavailable("nenhuma competência publicada até esta data")

        preferidos = await self._admin.list_preferred_products(customer_id)
        apelidos = {
            preferido.product_id: preferido.customer_alias for preferido in preferidos
        }
        ordem = {
            preferido.product_id: posicao for posicao, preferido in enumerate(preferidos)
        }

        if preferidos:
            linhas = await self._entries.list_items_for_products(
                scope.tenant_id, competencia, [p.product_id for p in preferidos]
            )
            # A ordem escolhida pelo cliente prevalece sobre a do catálogo.
            linhas.sort(key=lambda linha: ordem.get(linha[1].id, len(ordem)))
        else:
            linhas = await self._entries.list_items(scope.tenant_id, competencia)

        modo = ConversionMode(self._settings.icms_conversion_mode)
        itens: list[ResolvedItem] = []

        for entrada, produto, familia in linhas:
            sem_preco = entrada.availability in _SEM_PRECO
            preco_final = None
            aliquota = None
            trace = None

            if not sem_preco:
                # Uma regra ausente interrompe a lista inteira, de propósito:
                # entregar a lista sem o item que falhou faria o representante
                # cotar em cima de uma tabela silenciosamente incompleta.
                resolucao = await self._resolver.resolve(
                    tenant_id=scope.tenant_id,
                    origin_state=origin_state,
                    destination_state=localidade.state_code,
                    product_id=produto.id,
                    family_id=produto.family_id,
                    customer_id=cliente.id,
                    at=referencia,
                )
                convertido = convert_price(
                    base_price=entrada.base_price,
                    base_tax_rate=entrada.base_tax_rate,
                    resolution=resolucao,
                    mode=modo,
                )
                preco_final = convertido.final_price
                aliquota = convertido.tax_rate
                trace = convertido.trace

            itens.append(
                ResolvedItem(
                    product_id=produto.id,
                    sku=produto.sku,
                    family_name=familia.name,
                    display_name=apelidos.get(produto.id) or produto.commercial_name,
                    specification=produto.specification,
                    unit=produto.unit,
                    availability=entrada.availability.value,
                    base_price=None if sem_preco else entrada.base_price,
                    final_price=preco_final,
                    tax_rate=aliquota,
                    expected_arrival_date=entrada.expected_arrival_date,
                    arrival_note=entrada.arrival_note,
                    notes=entrada.notes,
                    trace=trace,
                )
            )

        return ResolvedPriceList(
            customer=cliente,
            location=localidade,
            reference_month=competencia,
            origin_state=origin_state or "",
            currency="BRL",
            items=itens,
        )
