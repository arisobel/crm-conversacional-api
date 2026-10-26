"""Respostas das leituras do representante pelo WhatsApp (W6).

O item de preço reaproveita `CurrentPriceListItemResponse`: é a mesma forma que
o Gateway já formata em produção, e um segundo formato faria o executor novo
precisar de um formatador novo sem nenhuma razão de domínio.
"""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from crm_api.schemas.customer_intake import OpenCustomerIntakeRequest
from crm_api.schemas.price_lists import CurrentPriceListItemResponse


class AssistantExecutionContext(BaseModel):
    """Identidade assinada de uma chamada feita pela Linha Assistente.

    O telefone identifica quem escreveu para a linha central. O CRM resolve o
    representante e exige uma conexão WhatsApp ativa dele; a referência de
    linha, quando o Gateway puder fornecê-la, é uma prova adicional.
    """

    assistant_line_phone_number_id: str = Field(pattern=r"^\d{5,64}$")
    representative_phone_e164: str = Field(min_length=8, max_length=20)
    request_id: str = Field(min_length=1, max_length=200)
    representative_line_reference: str | None = Field(default=None, min_length=1, max_length=200)


class AssistantSearchPriceItemsRequest(BaseModel):
    context: AssistantExecutionContext
    query: str = Field(min_length=2, max_length=120)


class AssistantLookupCustomersRequest(BaseModel):
    context: AssistantExecutionContext
    query: str = Field(min_length=2, max_length=120)


class AssistantCustomerPriceListRequest(BaseModel):
    context: AssistantExecutionContext


class AssistantCustomerIntakeRequest(BaseModel):
    context: AssistantExecutionContext
    intake: OpenCustomerIntakeRequest


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
    """Tabela de um cliente da carteira, ao preço publicado (ADR-032).

    Sem o `calculation_trace` de cada item, de propósito: ele existe para ser
    conferido item a item numa tela, e o WhatsApp não sabe exibir valores
    intermediários de cálculo. Quem precisa auditar o número abre o portal.
    """

    customer_id: UUID
    customer_name: str
    reference_month: date
    # Par de UFs da conversão de ICMS. Nulos no modo padrão: o Gateway escreve
    # "já com ICMS para <UF>" sempre que a UF de destino vem preenchida.
    origin_state: str | None = None
    destination_state: str | None = None
    currency: str
    items: list[CurrentPriceListItemResponse]
