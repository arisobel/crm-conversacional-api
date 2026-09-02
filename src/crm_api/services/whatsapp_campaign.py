"""Rascunho de campanha de WhatsApp: criação, consulta e cancelamento (F6.1).

Governam este módulo três decisões do ADR-028 e do plano F6:

**Nada dispara.** Não existe aqui chamada ao Gateway, à Meta ou a qualquer
transporte. Confirmar campanha é fluxo da F6.3/F6.4; este serviço conhece
apenas `DRAFT` e `CANCELLED`.

**A carteira decide quem entra.** Todo destinatário precisa ser cliente cuja
`owner_user_id` é o ator — para qualquer papel. A alçada de `ADMIN`/`MANAGER`
criarem em nome de outra carteira é pendência da F6.0; até ela ser decidida,
não existe caminho de código que a exerça, em vez de existir um caminho
"temporário" que a decisão depois teria de revogar.

**O rascunho é fotografia.** Critérios, público, template, variáveis e
destinatários são congelados na criação e nenhum método deste serviço os
altera. Corrigir é cancelar e criar outro rascunho — a revisão de alguém nunca
é reescrita por baixo.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from crm_api.models.user import UserRole
from crm_api.models.whatsapp_campaign import (
    CampaignStatus,
    RecipientStatus,
    WhatsappCampaign,
    WhatsappCampaignRecipient,
)
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.whatsapp_campaigns import WhatsappCampaignRepository

MAX_IDEMPOTENCY_KEY = 128
MAX_MOTIVO = 500


class CampaignNotFound(Exception):
    """Campanha inexistente, ou fora do alcance de quem pediu.

    O mesmo erro para os dois casos, de propósito: distinguir "não é sua" de
    "não existe" entregaria a existência de campanhas de outras carteiras.
    """


class CampaignNotCancellable(Exception):
    """Só rascunho é cancelável nesta fase; o resto ainda nem pode existir."""


class CustomerOutsidePortfolio(Exception):
    """Um destinatário não é cliente da carteira do ator."""


class ContactMismatch(Exception):
    """O contato informado não pertence ao cliente informado, ou está inativo."""


class DuplicateRecipient(Exception):
    """O mesmo destinatário apareceu duas vezes no rascunho."""


class MissingExclusionReason(Exception):
    """Linha sem contato só existe como exclusão, e exclusão exige motivo."""


class EmptyAudience(Exception):
    """Rascunho sem nenhum destinatário elegível não tem o que confirmar."""


class BlankField(ValueError):
    """Campo obrigatório veio vazio ou só com espaços."""


@dataclass(frozen=True)
class DraftRecipient:
    """Um alvo declarado por quem monta o rascunho.

    `contact_id` nulo registra exclusão prévia sem contato elegível e exige
    `excluded_reason`. `excluded_reason` com contato registra exclusão com
    contato conhecido — opt-out virá por aqui quando a F6.4 existir.
    """

    customer_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    excluded_reason: str | None = None


@dataclass(frozen=True)
class CreatedDraft:
    campaign: WhatsappCampaign
    # `False` quando a chave de idempotência já existia — quem chamou não deve
    # anunciar "rascunho criado" duas vezes sobre o mesmo comando.
    created: bool


class WhatsappCampaignService:
    def __init__(
        self,
        *,
        campaigns: WhatsappCampaignRepository,
        audit: AuditRepository,
    ) -> None:
        self._campaigns = campaigns
        self._audit = audit

    # -------------------------------------------------------------- criação

    @staticmethod
    def _snapshot_obrigatorio(value: dict, *, campo: str) -> dict:
        if not isinstance(value, dict) or not value:
            raise BlankField(f"{campo} precisa de conteúdo estruturado")
        return value

    @staticmethod
    def _chave(idempotency_key: str) -> str:
        limpa = idempotency_key.strip()
        if not limpa:
            raise BlankField("idempotency_key não pode ficar em branco")
        return limpa[:MAX_IDEMPOTENCY_KEY]

    async def _validar_destinatarios(
        self,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        recipients: list[DraftRecipient],
    ) -> list[tuple[DraftRecipient, dict]]:
        """Valida carteira, vínculo de contato e duplicidade, e monta snapshots.

        A validação inteira acontece antes de qualquer `add`: um rascunho com
        uma linha inválida não é gravado pela metade.
        """
        if not recipients:
            raise EmptyAudience("o rascunho precisa de pelo menos um destinatário")

        vistos: set[tuple[uuid.UUID, uuid.UUID | None]] = set()
        for alvo in recipients:
            chave = (alvo.customer_id, alvo.contact_id)
            if chave in vistos:
                raise DuplicateRecipient(str(alvo.customer_id))
            vistos.add(chave)
            if alvo.contact_id is None and not (
                alvo.excluded_reason and alvo.excluded_reason.strip()
            ):
                raise MissingExclusionReason(str(alvo.customer_id))

        clientes = await self._campaigns.customers_by_ids(
            tenant_id, [alvo.customer_id for alvo in recipients]
        )
        contatos = await self._campaigns.contacts_by_ids(
            tenant_id,
            [alvo.contact_id for alvo in recipients if alvo.contact_id is not None],
        )

        validados: list[tuple[DraftRecipient, dict]] = []
        for alvo in recipients:
            cliente = clientes.get(alvo.customer_id)
            # Cliente de outro tenant não veio no dicionário e cai aqui junto
            # com o inexistente — mesma mensagem, nada a revelar.
            if cliente is None or not cliente.active:
                raise CustomerOutsidePortfolio(str(alvo.customer_id))
            if cliente.owner_user_id != actor_user_id:
                raise CustomerOutsidePortfolio(str(alvo.customer_id))

            snapshot: dict = {
                "legal_name": cliente.legal_name,
                "owner_user_id": str(cliente.owner_user_id),
            }
            if alvo.contact_id is not None:
                contato = contatos.get(alvo.contact_id)
                if (
                    contato is None
                    or contato.customer_id != alvo.customer_id
                    or not contato.active
                ):
                    raise ContactMismatch(str(alvo.contact_id))
                snapshot["contact_name"] = contato.name
                snapshot["whatsapp_e164"] = contato.whatsapp_e164
            validados.append((alvo, snapshot))

        if not any(alvo.excluded_reason is None for alvo, _ in validados):
            raise EmptyAudience("todos os destinatários do rascunho estão excluídos")
        return validados

    async def create_draft(
        self,
        tenant_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
        idempotency_key: str,
        criteria: dict,
        template: dict,
        audience_summary: dict,
        recipients: list[DraftRecipient],
        variables: dict | None = None,
        request_id: str | None = None,
    ) -> CreatedDraft:
        """Cria o rascunho, ou devolve o que este comando já criou.

        `actor_role` entra na assinatura e na auditoria, mas hoje não amplia
        alçada nenhuma: qualquer papel só monta rascunho sobre clientes de que
        é titular. Ver a nota de módulo sobre a pendência da F6.0.
        """
        chave = self._chave(idempotency_key)

        existente = await self._campaigns.by_idempotency_key(tenant_id, chave)
        if existente is not None:
            return CreatedDraft(campaign=existente, created=False)

        criterios = self._snapshot_obrigatorio(criteria, campo="critérios")
        modelo = self._snapshot_obrigatorio(template, campo="template")
        resumo = self._snapshot_obrigatorio(audience_summary, campo="resumo de audiência")
        validados = await self._validar_destinatarios(tenant_id, actor_user_id, recipients)

        campanha = WhatsappCampaign(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            created_by_user_id=actor_user_id,
            representative_user_id=actor_user_id,
            idempotency_key=chave,
            status=CampaignStatus.DRAFT,
            criteria_snapshot=criterios,
            audience_summary_snapshot=resumo,
            template_snapshot=modelo,
            variables_snapshot=variables or None,
        )

        elegiveis = 0
        excluidos = 0
        linhas: list[WhatsappCampaignRecipient] = []
        for alvo, snapshot in validados:
            excluido = alvo.excluded_reason is not None
            elegiveis += 0 if excluido else 1
            excluidos += 1 if excluido else 0
            linhas.append(
                WhatsappCampaignRecipient(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    campaign_id=campanha.id,
                    customer_id=alvo.customer_id,
                    contact_id=alvo.contact_id,
                    representative_user_id=actor_user_id,
                    recipient_snapshot=snapshot,
                    status=RecipientStatus.EXCLUDED if excluido else RecipientStatus.PENDING,
                    excluded_reason=(
                        alvo.excluded_reason.strip()[:MAX_MOTIVO] if excluido else None
                    ),
                )
            )

        # A checagem de idempotência acima é ler-depois-escrever; entre a
        # leitura e a gravação cabe outra requisição com a mesma chave. Quem
        # decide é a unicidade do banco; aqui só recuperamos a que venceu.
        try:
            async with self._campaigns.savepoint():
                self._campaigns.add(campanha)
                for linha in linhas:
                    self._campaigns.add(linha)
                self._audit.record(
                    action="WHATSAPP_CAMPAIGN_DRAFT_CREATED",
                    entity="whatsapp_campaigns",
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    entity_id=campanha.id,
                    after={
                        "recipients_total": len(linhas),
                        "recipients_eligible": elegiveis,
                        "recipients_excluded": excluidos,
                        "criteria": criterios,
                        "actor_role": actor_role.value,
                    },
                    request_id=request_id,
                )
                await self._campaigns.flush()
        except IntegrityError:
            vencedora = await self._campaigns.by_idempotency_key(tenant_id, chave)
            if vencedora is None:
                # A violação foi de outra restrição; não é nossa para tratar.
                raise
            return CreatedDraft(campaign=vencedora, created=False)

        return CreatedDraft(campaign=campanha, created=True)

    # ------------------------------------------------------------- consulta

    @staticmethod
    def _recorte(actor_user_id: uuid.UUID, actor_role: UserRole) -> uuid.UUID | None:
        """`None` é "todo o tenant" e só sai para `ADMIN` e `MANAGER`."""
        return actor_user_id if actor_role is UserRole.REPRESENTATIVE else None

    async def get_campaign(
        self,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
    ) -> tuple[WhatsappCampaign, list[WhatsappCampaignRecipient]]:
        campanha = await self._campaigns.get(
            tenant_id,
            campaign_id,
            representative_user_id=self._recorte(actor_user_id, actor_role),
        )
        if campanha is None:
            raise CampaignNotFound
        destinatarios = await self._campaigns.recipients(tenant_id, campanha.id)
        return campanha, destinatarios

    async def list_campaigns(
        self,
        tenant_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
        status: CampaignStatus | None = None,
        representative_user_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WhatsappCampaign], int]:
        """Lista recortada pelo papel.

        Para `REPRESENTATIVE`, o filtro por representante do corpo é ignorado e
        o recorte é sempre ele mesmo — o mesmo desenho do `owner_user_id`
        ignorado no cadastro de cliente (R2). `ADMIN` e `MANAGER` veem o tenant
        e podem filtrar por representante.
        """
        recorte = self._recorte(actor_user_id, actor_role)
        filtro = recorte if recorte is not None else representative_user_id
        linhas = await self._campaigns.list(
            tenant_id,
            representative_user_id=filtro,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await self._campaigns.count(
            tenant_id, representative_user_id=filtro, status=status
        )
        return linhas, total

    # --------------------------------------------------------- cancelamento

    async def cancel_draft(
        self,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
        request_id: str | None = None,
    ) -> WhatsappCampaign:
        """Cancela um rascunho. Idempotente: cancelar o já cancelado é no-op.

        O alcance é o do responsável congelado, para **qualquer papel**: a
        alçada de `ADMIN`/`MANAGER` cancelarem campanha alheia é a mesma
        pendência da F6.0 que trava a criação em nome de terceiros.
        """
        campanha = await self._campaigns.get(
            tenant_id, campaign_id, representative_user_id=actor_user_id
        )
        if campanha is None:
            raise CampaignNotFound
        if campanha.status is CampaignStatus.CANCELLED:
            return campanha
        if campanha.status is not CampaignStatus.DRAFT:
            raise CampaignNotCancellable(campanha.status.value)

        campanha.status = CampaignStatus.CANCELLED
        self._audit.record(
            action="WHATSAPP_CAMPAIGN_CANCELLED",
            entity="whatsapp_campaigns",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=campanha.id,
            before={"status": CampaignStatus.DRAFT.value},
            after={"status": CampaignStatus.CANCELLED.value, "actor_role": actor_role.value},
            request_id=request_id,
        )
        await self._campaigns.flush()
        return campanha
