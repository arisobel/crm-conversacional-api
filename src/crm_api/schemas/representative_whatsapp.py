"""Respostas das leituras do representante pelo WhatsApp (W6).

O item de preço reaproveita `CurrentPriceListItemResponse`: é a mesma forma que
o Gateway já formata em produção, e um segundo formato faria o executor novo
precisar de um formatador novo sem nenhuma razão de domínio.
"""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from crm_api.schemas.price_lists import CurrentPriceListItemResponse


class PriceItemsResponse(BaseModel):
    reference_month: date
    items: list[CurrentPriceListItemResponse]


class CustomerMatchResponse(BaseModel):
    customer_id: UUID
    legal_name: str
    trade_name: str | None = None
    document_number: str | None = None
    state_code: str


class CustomerMatchesResponse(BaseModel):
    # `truncated` diz que a busca foi ampla demais, sem obrigar quem consome a
    # comparar tamanhos com um limite que ele não conhece.
    matches: list[CustomerMatchResponse]
    truncated: bool = Field(
        description="Há mais candidatos do que os devolvidos; peça um termo mais específico."
    )


class ResolvedCustomerPriceListResponse(BaseModel):
    """Tabela convertida de um cliente da carteira.

    Sem o `calculation_trace` de cada item, de propósito: ele existe para ser
    conferido item a item numa tela, e o WhatsApp não sabe exibir valores
    intermediários de cálculo. Quem precisa auditar o número abre o portal.
    """

    customer_id: UUID
    customer_name: str
    reference_month: date
    origin_state: str
    destination_state: str
    currency: str
    items: list[CurrentPriceListItemResponse]
