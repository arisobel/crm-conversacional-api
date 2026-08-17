"""As três leituras que um representante faz pelo WhatsApp (W6).

Duas decisões de alcance governam este módulo, e as duas são mais restritivas do
que o portal:

**A carteira é sempre a de quem escreveu, qualquer que seja o papel.** No portal,
`ADMIN` e `MANAGER` enxergam o tenant inteiro; aqui não. O canal autentica por
número de telefone, que é prova de identidade mais fraca que uma sessão com
senha, e por isso recebe o escopo mais estreito que ainda é útil. Quem precisa
da base toda usa o portal.

**A busca de artigo devolve preço-base, sem conversão.** Não há cliente na
pergunta, logo não há UF de destino — e inventar uma seria escolher a praça do
cliente por conta própria. A conversão só aparece na terceira operação, onde o
cliente é explícito.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from crm_api.core.config import Settings
from crm_api.models.customer import Customer
from crm_api.models.pricing import AvailabilityStatus
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.portfolio import (
    CustomerFilters,
    CustomerPortfolioRepository,
    PortfolioScope,
)
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.schemas.price_lists import CurrentPriceListItemResponse
from crm_api.services.customer_price_list import CustomerPriceListService
from crm_api.services.product_search import matches_search_terms, search_tokens
from crm_api.services.whatsapp_actor import ActorRole, WhatsappActor

# Mesma regra da tabela do cliente: indisponível não exibe preço, porque não
# haveria preço a exibir.
_SEM_PRECO = {
    AvailabilityStatus.OUT_OF_STOCK,
    AvailabilityStatus.SUSPENDED,
    AvailabilityStatus.CONSULT,
}

# Teto de candidatos devolvidos na busca de cliente. Três é o que o Gateway
# consegue apresentar numa mensagem sem virar parede de texto, e é o mesmo
# número que o `GW-023` prevê para recuperação de ambiguidade.
MAX_CANDIDATOS = 3


class NotARepresentative(Exception):
    """Quem escreveu não é um usuário do portal.

    Não deveria acontecer: o manifesto de cliente não anuncia estas ações, e o
    Gateway só executa o que o manifesto autoriza. É a segunda tranca.
    """


class NoPublishedCompetence(Exception):
    """Nenhuma competência publicada até a data pedida."""


@dataclass(frozen=True)
class CustomerMatch:
    customer_id: uuid.UUID
    legal_name: str
    trade_name: str | None
    document_number: str | None
    state_code: str


@dataclass(frozen=True)
class PriceItems:
    reference_month: date
    items: list[CurrentPriceListItemResponse]


class RepresentativeWhatsappService:
    def __init__(
        self,
        *,
        portfolio: CustomerPortfolioRepository,
        admin: CustomerAdminRepository,
        entries: PriceEntryRepository,
        resolved: CustomerPriceListService,
        settings: Settings,
    ) -> None:
        self._portfolio = portfolio
        self._admin = admin
        self._entries = entries
        self._resolved = resolved
        self._settings = settings

    @staticmethod
    def _escopo(actor: WhatsappActor, tenant_id: uuid.UUID) -> PortfolioScope:
        if actor.role is not ActorRole.REPRESENTATIVE or actor.user_id is None:
            raise NotARepresentative("this action is only available to portal users")
        return PortfolioScope(tenant_id=tenant_id, owner_user_id=actor.user_id)

    async def search_price_items(
        self,
        actor: WhatsappActor,
        tenant_id: uuid.UUID,
        query: str,
        *,
        at: datetime | None = None,
    ) -> PriceItems:
        """Artigo na competência vigente, em preço-base.

        A tabela do mês é do tenant, não do cliente, então não há escopo de
        carteira a aplicar — mas o ator ainda precisa ser um usuário do portal.
        """
        self._escopo(actor, tenant_id)

        momento = (at or datetime.now(UTC)).date()
        competencia = await self._entries.latest_month(tenant_id, at=momento)
        if competencia is None:
            raise NoPublishedCompetence("nenhuma competência publicada até esta data")

        termos = search_tokens(query)
        linhas = await self._entries.list_items(tenant_id, competencia)
        itens = [
            CurrentPriceListItemResponse(
                product_id=produto.id,
                family_name=familia.name,
                sku=produto.sku,
                display_name=produto.commercial_name,
                specification=produto.specification,
                unit=produto.unit,
                availability=entrada.availability.value,
                base_price=(None if entrada.availability in _SEM_PRECO else entrada.base_price),
                expected_arrival_date=entrada.expected_arrival_date,
                arrival_note=entrada.arrival_note,
                notes=entrada.notes,
            )
            for entrada, produto, familia in linhas
        ]
        return PriceItems(
            reference_month=competencia,
            items=[item for item in itens if termos and matches_search_terms(item, termos)],
        )

    async def lookup_customers(
        self, actor: WhatsappActor, tenant_id: uuid.UUID, query: str
    ) -> list[CustomerMatch]:
        """Clientes da carteira de quem escreveu que casam com o termo.

        Devolve no máximo `MAX_CANDIDATOS + 1`: o excedente é o sinal de que a
        busca foi ampla demais, e quem formata a mensagem decide entre listar e
        pedir refinamento — sem estado conversacional, que ainda não existe do
        outro lado.
        """
        escopo = self._escopo(actor, tenant_id)
        encontrados = await self._portfolio.list_customers(
            escopo,
            CustomerFilters(search=query, active=True),
            limit=MAX_CANDIDATOS + 1,
            offset=0,
        )
        return [self._match(cliente) for cliente, _ in encontrados]

    @staticmethod
    def _match(cliente: Customer) -> CustomerMatch:
        return CustomerMatch(
            customer_id=cliente.id,
            legal_name=cliente.legal_name,
            trade_name=cliente.trade_name,
            document_number=cliente.document_number,
            state_code=cliente.state_code,
        )

    async def customer_price_list(
        self,
        actor: WhatsappActor,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        origin_state: str | None,
        at: datetime | None = None,
    ):
        """Tabela de um cliente da carteira, convertida para a UF dele.

        Delega ao serviço da R4 — o mesmo que o portal usa —, então produtos
        preferidos, localidade padrão e resolução de ICMS por especificidade não
        são reimplementados aqui. As exceções de domínio sobem para a rota.

        **`whatsapp_icms_enabled` não é consultado de propósito.** Aquele
        interruptor existe porque, na tabela do cliente, o número convertido vai
        direto a quem compra, sem ninguém conferir. Aqui o destinatário é o
        representante — exatamente a pessoa que o interruptor descreve como
        capaz de conferir o `trace` antes de cotar. É o caso do portal, num
        canal diferente.
        """
        escopo = self._escopo(actor, tenant_id)
        return await self._resolved.resolve(
            escopo,
            customer_id,
            origin_state=origin_state,
            at=(at or datetime.now(UTC)).date(),
        )
