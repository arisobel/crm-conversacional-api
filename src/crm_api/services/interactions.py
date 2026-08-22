"""Ingestão, leitura e expurgo do histórico de interações.

O CRM recebe os eventos por push do Gateway (ADR-016). Três decisões moldam
este módulo:

1. **Reentrância.** O Gateway não pode perder eventos por causa de uma falha de
   rede, então ele reenvia; reenviar não pode duplicar a linha do tempo.
2. **Nada órfão.** Um evento cujo telefone não corresponde a cliente nem a
   usuário do portal é recusado com motivo, não gravado sem dono. Um registro
   sem dono não apareceria em tela alguma e ainda assim guardaria conteúdo de
   conversa.
3. **Um item ruim não derruba o lote.** Cada evento é gravado em um savepoint
   próprio; o lote responde item a item.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.interaction import (
    GATEWAY_SOURCE,
    NOTE_CHANNELS,
    PORTAL_SOURCE,
    WHATSAPP_CHANNEL,
    CustomerInteraction,
    InteractionDirection,
    InteractionKind,
)
from crm_api.models.user import UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.interactions import InteractionRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository, PortfolioScope
from crm_api.services.customers import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.services.portfolio import CustomerNotInScope

# Corta o conteúdo antes de gravar. A projeção existe para dar contexto ao
# representante, não para ser um arquivo da conversa — que continua no Gateway.
_LIMITE_RESUMO = 2000


class RetentionNotConfigured(Exception):
    """Expurgo pedido sem política de retenção definida."""


class EmptyNote(Exception):
    """Nota sem texto. Uma linha em branco na ficha não registra nada."""


class UnknownNoteChannel(Exception):
    """Meio fora da lista que o portal oferece."""


class NoteNotFound(Exception):
    """Nota inexistente neste tenant."""


class NotEditable(Exception):
    """Tentativa de reescrever um evento de canal, que é imutável por desenho."""


class NoteNotOwned(Exception):
    """Representante tentando corrigir a nota de outro."""


class Outcome(StrEnum):
    CREATED = "CREATED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class IncomingInteraction:
    external_ref: str
    direction: InteractionDirection
    occurred_at: datetime
    whatsapp_e164: str | None = None
    customer_id: uuid.UUID | None = None
    source: str = GATEWAY_SOURCE
    channel: str = WHATSAPP_CHANNEL
    summary: str | None = None
    payload: dict | None = None


@dataclass(frozen=True)
class IngestOutcome:
    external_ref: str
    outcome: Outcome
    interaction_id: uuid.UUID | None = None
    reason: str | None = None


@dataclass
class IngestReport:
    results: list[IngestOutcome]

    def _quantos(self, outcome: Outcome) -> int:
        return sum(1 for resultado in self.results if resultado.outcome is outcome)

    @property
    def created(self) -> int:
        return self._quantos(Outcome.CREATED)

    @property
    def duplicated(self) -> int:
        return self._quantos(Outcome.DUPLICATE)

    @property
    def rejected(self) -> int:
        return self._quantos(Outcome.REJECTED)


def _em_utc(momento: datetime) -> datetime:
    """SQLite devolve `datetime` ingênuo; PostgreSQL preserva o fuso."""
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


class InteractionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        interactions: InteractionRepository,
        portfolio: CustomerPortfolioRepository,
        audit: AuditRepository,
    ) -> None:
        self._session = session
        self._interactions = interactions
        self._portfolio = portfolio
        self._audit = audit

    # -------------------------------------------------------------- ingestão

    async def ingest(
        self, *, tenant_id: uuid.UUID, eventos: list[IncomingInteraction]
    ) -> IngestReport:
        resultados: list[IngestOutcome] = []
        # Uma consulta por origem em vez de uma por evento. O índice único ainda
        # é a garantia final; isto só evita o caminho da exceção no caso comum.
        conhecidos: dict[str, set[str]] = {}
        for origem in {evento.source for evento in eventos}:
            conhecidos[origem] = await self._interactions.existing_refs(
                tenant_id, origem, [e.external_ref for e in eventos if e.source == origem]
            )

        for evento in eventos:
            if evento.external_ref in conhecidos[evento.source]:
                resultados.append(
                    IngestOutcome(evento.external_ref, Outcome.DUPLICATE)
                )
                continue

            try:
                dono = await self._resolver(tenant_id, evento)
            except _ResolutionFailed as falha:
                resultados.append(
                    IngestOutcome(evento.external_ref, Outcome.REJECTED, reason=str(falha))
                )
                continue

            interacao = CustomerInteraction(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                kind=dono.kind,
                customer_id=dono.customer_id,
                actor_user_id=dono.actor_user_id,
                contact_id=dono.contact_id,
                channel=evento.channel,
                direction=evento.direction,
                source=evento.source,
                external_ref=evento.external_ref,
                occurred_at=_em_utc(evento.occurred_at),
                summary=(evento.summary or "")[:_LIMITE_RESUMO] or None,
                payload=evento.payload,
            )
            try:
                # Savepoint por item: uma violação de unicidade em corrida
                # invalidaria a transação inteira e derrubaria o lote junto.
                async with self._session.begin_nested():
                    self._interactions.add(interacao)
            except IntegrityError:
                resultados.append(IngestOutcome(evento.external_ref, Outcome.DUPLICATE))
                continue

            # Dois eventos com a mesma referência dentro do mesmo lote: o
            # segundo é duplicata do primeiro, ainda não visível no banco.
            conhecidos[evento.source].add(evento.external_ref)
            resultados.append(
                IngestOutcome(evento.external_ref, Outcome.CREATED, interaction_id=interacao.id)
            )

        return IngestReport(results=resultados)

    async def _resolver(
        self, tenant_id: uuid.UUID, evento: IncomingInteraction
    ) -> "_Owner":
        if evento.customer_id is not None:
            escopo = PortfolioScope(tenant_id=tenant_id, owner_user_id=None)
            encontrado = await self._portfolio.get_customer(escopo, evento.customer_id)
            if encontrado is None:
                raise _ResolutionFailed("customer not found in tenant")
            return _Owner(customer_id=evento.customer_id)

        if not evento.whatsapp_e164:
            raise _ResolutionFailed("either customer_id or whatsapp_e164 is required")
        try:
            telefone = normalize_whatsapp_e164(evento.whatsapp_e164)
        except InvalidWhatsappNumber as error:
            raise _ResolutionFailed(str(error)) from error

        par = await self._interactions.resolve_contact(tenant_id, telefone)
        if par is not None:
            contato, cliente = par
            return _Owner(customer_id=cliente.id, contact_id=contato.id)

        # Só depois de o contato falhar. A ordem importa: um telefone não pode
        # ser os dois — o cadastro recusa a colisão (ADR-022) —, mas se um dia
        # escapar, tratar como cliente é a leitura de menor alçada.
        usuario = await self._interactions.resolve_portal_user(tenant_id, telefone)
        if usuario is not None:
            return _Owner(actor_user_id=usuario.id)

        raise _ResolutionFailed("no customer contact or portal user matches this phone")

    # ------------------------------------------------------------ nota manual

    async def register_note(
        self,
        *,
        scope: PortfolioScope,
        customer_id: uuid.UUID,
        author_user_id: uuid.UUID,
        summary: str,
        channel: str,
        direction: InteractionDirection | None,
        occurred_at: datetime | None = None,
        contact_id: uuid.UUID | None = None,
    ) -> CustomerInteraction:
        """Registra na ficha uma conversa que aconteceu fora do canal.

        O autor é sempre quem está logado, nunca um campo do formulário: a nota
        é o relato dele, e deixar escolher o autor permitiria atribuir a outro
        representante uma conversa que nunca houve.
        """
        if await self._portfolio.get_customer(scope, customer_id) is None:
            raise CustomerNotInScope

        texto = summary.strip()
        if not texto:
            raise EmptyNote
        if channel not in NOTE_CHANNELS:
            raise UnknownNoteChannel(channel)

        nota = CustomerInteraction(
            id=uuid.uuid4(),
            tenant_id=scope.tenant_id,
            kind=InteractionKind.REPRESENTATIVE_NOTE,
            customer_id=customer_id,
            actor_user_id=author_user_id,
            contact_id=contact_id,
            channel=channel,
            direction=direction,
            source=PORTAL_SOURCE,
            # A nota não referencia sistema externo nenhum — ela é a própria
            # origem. Usar o id dela mantém `(tenant, source, external_ref)`
            # único sem inventar uma referência que não existe.
            external_ref="",
            occurred_at=_em_utc(occurred_at or datetime.now(UTC)),
            summary=texto[:_LIMITE_RESUMO],
        )
        nota.external_ref = str(nota.id)
        self._interactions.add(nota)

        self._audit.record(
            action="INTERACTION_NOTE_CREATED",
            entity="customer_interactions",
            tenant_id=scope.tenant_id,
            actor_user_id=author_user_id,
            entity_id=nota.id,
            after={
                "customer_id": str(customer_id),
                "channel": channel,
                "direction": direction.value if direction else None,
                "summary": nota.summary,
            },
        )
        return nota

    async def edit_note(
        self,
        *,
        scope: PortfolioScope,
        note_id: uuid.UUID,
        editor_user_id: uuid.UUID,
        editor_role: UserRole,
        summary: str,
        now: datetime | None = None,
    ) -> CustomerInteraction:
        """Corrige o texto de uma nota já registrada.

        É a única escrita que altera uma linha desta tabela, e vale só para
        nota. Evento de canal continua imutável: ele relata o que aconteceu, e
        reescrever o que o cliente disse seria falsificar a projeção.
        """
        nota = await self._interactions.get_by_id(scope.tenant_id, note_id)
        if nota is None:
            raise NoteNotFound
        if nota.kind is not InteractionKind.REPRESENTATIVE_NOTE:
            raise NotEditable
        # Escopo pelo cliente, não pela nota: um representante que perdeu a
        # titularidade da conta deixa de alcançar o histórico dela junto.
        if nota.customer_id is None or (
            await self._portfolio.get_customer(scope, nota.customer_id) is None
        ):
            raise CustomerNotInScope
        # Autor corrige o que escreveu; gestão corrige qualquer uma. Um
        # representante reescrevendo a nota de outro apagaria o relato alheio.
        if editor_role not in (UserRole.ADMIN, UserRole.MANAGER) and (
            nota.actor_user_id != editor_user_id
        ):
            raise NoteNotOwned

        texto = summary.strip()
        if not texto:
            raise EmptyNote

        anterior = nota.summary
        nota.summary = texto[:_LIMITE_RESUMO]
        nota.edited_at = _em_utc(now or datetime.now(UTC))

        self._audit.record(
            action="INTERACTION_NOTE_EDITED",
            entity="customer_interactions",
            tenant_id=scope.tenant_id,
            actor_user_id=editor_user_id,
            entity_id=nota.id,
            before={"summary": anterior},
            after={"summary": nota.summary},
        )
        return nota

    # --------------------------------------------------------------- leitura

    async def timeline(
        self, scope: PortfolioScope, customer_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[CustomerInteraction], int]:
        if await self._portfolio.get_customer(scope, customer_id) is None:
            raise CustomerNotInScope
        return (
            await self._interactions.list_timeline(
                scope.tenant_id, customer_id, limit=limit, offset=offset
            ),
            await self._interactions.count_timeline(scope.tenant_id, customer_id),
        )

    async def actor_timeline(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[CustomerInteraction], int]:
        """Conversa de um usuário do portal pelo WhatsApp.

        Sem escopo de carteira porque não há carteira envolvida: o dono do
        histórico é o próprio usuário. Quem pode alcançá-lo é decidido na rota.
        """
        return (
            await self._interactions.list_actor_timeline(
                tenant_id, user_id, limit=limit, offset=offset
            ),
            await self._interactions.count_actor_timeline(tenant_id, user_id),
        )

    async def last_interactions(
        self, tenant_id: uuid.UUID, customer_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, datetime]:
        return await self._interactions.last_interaction_map(tenant_id, customer_ids)

    # --------------------------------------------------------------- expurgo

    async def purge(
        self,
        *,
        tenant_id: uuid.UUID,
        retention_days: int | None,
        actor_user_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> int:
        """Remove interações mais antigas que a política de retenção.

        Sem política definida o expurgo **falha** em vez de assumir um prazo:
        quanto tempo o histórico de conversa pode viver é decisão de LGPD (Q3),
        não um valor padrão que o código escolhe sozinho.
        """
        if retention_days is None or retention_days <= 0:
            raise RetentionNotConfigured(
                "defina CRM_INTERACTION_RETENTION_DAYS antes de expurgar"
            )

        corte = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        removidas = await self._interactions.delete_before(tenant_id, corte)
        self._audit.record(
            action="INTERACTIONS_PURGED",
            entity="customer_interactions",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            after={
                "retention_days": retention_days,
                "cutoff": corte.isoformat(),
                "removed": removidas,
            },
        )
        return removidas


@dataclass(frozen=True)
class _Owner:
    """A quem o evento de canal pertence — exatamente um dos dois.

    A ingestão nunca produz `REPRESENTATIVE_NOTE`: nota nasce no portal, não no
    Gateway. Por isso `kind` aqui só tem duas saídas possíveis.
    """

    customer_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None

    @property
    def kind(self) -> InteractionKind:
        return (
            InteractionKind.CUSTOMER_CHANNEL
            if self.customer_id is not None
            else InteractionKind.ACTOR_CHANNEL
        )


class _ResolutionFailed(Exception):
    """Falha ao ligar o evento a um dono. Interna: vira motivo na resposta."""
