"""Pré-cadastro de cliente: abertura pelo WhatsApp, resolução pelo portal (W7).

Governa este módulo o mesmo princípio do resto do canal: **o WhatsApp nunca
concede alçada que o portal já não conceda — ele só antecipa digitação.** O R2 já
permite que um `REPRESENTATIVE` crie cliente pelo portal e vire titular dele;
abrir pré-cadastro por mensagem não acrescenta poder, apenas adia a conferência.

Por isso a operação de escrita **não cria cliente**. Ela abre um registro numa
fila. Aceitar é ato separado, feito no portal, por gente com sessão — e é só ali
que o cliente passa a existir, que o telefone dele entra no roster e que o
Gateway começa a atendê-lo.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from crm_api.core.phone import normalize_whatsapp_e164
from crm_api.core.states import normalize_state_code
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.customer_intake import CustomerIntake, IntakeSource, IntakeStatus
from crm_api.models.user import UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.customer_intakes import CustomerIntakeRepository
from crm_api.repositories.portfolio import PortfolioScope
from crm_api.repositories.users import UserRepository
from crm_api.services.customer_admin import CustomerAdminService
from crm_api.services.whatsapp_actor import ActorRole, WhatsappActor

# Teto do texto livre. Não é limite de banco — é o ponto em que uma "preferência
# de material" deixou de ser preferência e virou pedido, que não é o que esta
# fila resolve.
MAX_PREFERENCIA = 500
MAX_RAZAO_SOCIAL = 200
MAX_MOTIVO = 500


class NotARepresentative(Exception):
    """Quem escreveu não é usuário do portal.

    Segunda tranca: o manifesto de cliente não anuncia esta ação, e o Gateway só
    executa o que o manifesto autoriza.
    """


class IntakeNotFound(Exception):
    """Pré-cadastro inexistente, ou fora do alcance de quem pediu."""


class IntakeAlreadyResolved(Exception):
    """Já foi aceito ou rejeitado; resolver de novo mudaria história."""


class WhatsappAlreadyUsed(Exception):
    """O telefone já é contato de cliente ou usuário do portal neste tenant."""


class BlankField(ValueError):
    """Campo obrigatório veio vazio ou só com espaços."""


@dataclass(frozen=True)
class OpenedIntake:
    intake: CustomerIntake
    # `False` quando a chave de idempotência já existia. Quem responde ao
    # representante usa isto para não dizer "abri o pré-cadastro" duas vezes
    # sobre a mesma mensagem.
    created: bool


class CustomerIntakeService:
    def __init__(
        self,
        *,
        intakes: CustomerIntakeRepository,
        admin: CustomerAdminRepository,
        users: UserRepository,
        customers: CustomerAdminService,
        audit: AuditRepository,
    ) -> None:
        self._intakes = intakes
        self._admin = admin
        self._users = users
        self._customers = customers
        self._audit = audit

    # ------------------------------------------------------------- abertura

    @staticmethod
    def _autor(actor: WhatsappActor) -> uuid.UUID:
        if actor.role is not ActorRole.REPRESENTATIVE or actor.user_id is None:
            raise NotARepresentative("this action is only available to portal users")
        return actor.user_id

    @staticmethod
    def _texto(value: str, *, campo: str, maximo: int) -> str:
        limpo = value.strip()
        if not limpo:
            raise BlankField(f"{campo} não pode ficar em branco")
        return limpo[:maximo]

    async def _telefone_livre(self, tenant_id: uuid.UUID, raw: str) -> str:
        """Canoniza e recusa telefone já usado, nas **duas** tabelas.

        A checagem cruzada acontece aqui, e não só na aceitação, porque avisar o
        representante na hora custa uma frase e descobrir na fila custa uma
        conversa. Ela é repetida na aceitação de propósito: entre abrir e aceitar
        pode passar uma semana, e nesse meio alguém pode ter cadastrado o número.
        """
        phone = normalize_whatsapp_e164(raw)
        if await self._admin.whatsapp_exists(tenant_id, phone):
            raise WhatsappAlreadyUsed(phone)
        if await self._users.whatsapp_exists(tenant_id, phone):
            raise WhatsappAlreadyUsed(phone)
        return phone

    async def open(
        self,
        actor: WhatsappActor,
        tenant_id: uuid.UUID,
        *,
        idempotency_key: str,
        legal_name: str,
        state_code: str,
        whatsapp_e164: str | None = None,
        preferred_products_text: str | None = None,
        request_id: str | None = None,
    ) -> OpenedIntake:
        """Abre o pré-cadastro, ou devolve o que esta mensagem já abriu.

        A reentrega devolve o registro **em qualquer estado**, inclusive aceito:
        um webhook repetido depois de alguém aceitar não pode abrir um segundo
        pré-cadastro do mesmo cliente.
        """
        autor = self._autor(actor)

        existente = await self._intakes.by_idempotency_key(tenant_id, idempotency_key)
        if existente is not None:
            return OpenedIntake(intake=existente, created=False)

        intake = self._novo(
            tenant_id,
            autor,
            idempotency_key=idempotency_key,
            legal_name=legal_name,
            state_code=state_code,
            whatsapp_e164=await self._telefone_livre(tenant_id, whatsapp_e164)
            if whatsapp_e164
            else None,
            preferred_products_text=preferred_products_text,
        )

        # A checagem acima é ler-depois-escrever, e entre a leitura e a gravação
        # cabe outra requisição com a mesma chave — o Gateway reentrega webhook, e
        # duas entregas simultâneas da mesma mensagem são o caso normal, não o
        # excepcional. Quem decide é a unicidade do banco; aqui só recuperamos.
        try:
            async with self._intakes.savepoint():
                self._intakes.add(intake)
                self._audit.record(
                    action="CUSTOMER_INTAKE_OPENED",
                    entity="customer_intakes",
                    tenant_id=tenant_id,
                    actor_user_id=autor,
                    entity_id=intake.id,
                    after={
                        "legal_name": intake.legal_name,
                        "state_code": intake.state_code,
                        "has_whatsapp": intake.whatsapp_e164 is not None,
                        "source": intake.source,
                    },
                    request_id=request_id,
                )
                await self._intakes.flush()
        except IntegrityError:
            # Perdemos a corrida. O `SAVEPOINT` desfez a inserção e a auditoria
            # junto — não houve abertura a auditar —, e a sessão continua viva
            # para reler a linha que venceu.
            vencedor = await self._intakes.by_idempotency_key(tenant_id, idempotency_key)
            if vencedor is None:
                # A violação foi de outra restrição; não é nossa para tratar.
                raise
            return OpenedIntake(intake=vencedor, created=False)

        return OpenedIntake(intake=intake, created=True)

    def _novo(
        self,
        tenant_id: uuid.UUID,
        autor: uuid.UUID,
        *,
        idempotency_key: str,
        legal_name: str,
        state_code: str,
        whatsapp_e164: str | None,
        preferred_products_text: str | None,
    ) -> CustomerIntake:
        return CustomerIntake(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            created_by_user_id=autor,
            source=IntakeSource.WHATSAPP.value,
            idempotency_key=idempotency_key,
            legal_name=self._texto(legal_name, campo="razão social", maximo=MAX_RAZAO_SOCIAL),
            state_code=normalize_state_code(state_code),
            whatsapp_e164=whatsapp_e164,
            preferred_products_text=(
                preferred_products_text.strip()[:MAX_PREFERENCIA]
                if preferred_products_text and preferred_products_text.strip()
                else None
            ),
            status=IntakeStatus.PENDING,
        )

    # ------------------------------------------------------------- resolução

    async def _alcancavel(
        self,
        tenant_id: uuid.UUID,
        intake_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
    ) -> CustomerIntake:
        intake = await self._intakes.get(tenant_id, intake_id)
        if intake is None:
            raise IntakeNotFound
        # `REPRESENTATIVE` alcança apenas os que ele abriu. Mesmo corpo de erro de
        # um id inexistente: distinguir "não é seu" de "não existe" entregaria a
        # existência de pré-cadastros de outras carteiras.
        if actor_role is UserRole.REPRESENTATIVE and intake.created_by_user_id != actor_user_id:
            raise IntakeNotFound
        if intake.status is not IntakeStatus.PENDING:
            raise IntakeAlreadyResolved
        return intake

    async def accept(
        self,
        tenant_id: uuid.UUID,
        intake_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
        legal_name: str | None = None,
        state_code: str | None = None,
        trade_name: str | None = None,
        document_number: str | None = None,
        contact_name: str | None = None,
        request_id: str | None = None,
    ) -> CustomerIntake:
        """Cria o cliente e encerra o pré-cadastro, na mesma transação.

        Os campos podem ser corrigidos na aceitação: o que o representante ditou
        no WhatsApp é ponto de partida, não verdade cadastral. O que **não** muda
        é o titular — o cliente nasce na carteira de quem abriu o pré-cadastro,
        não de quem aceitou.

        A criação do cliente é delegada ao `CustomerAdminService`, o mesmo que o
        portal usa, para que localidade padrão, histórico de titularidade e
        auditoria não tenham uma segunda implementação capaz de divergir.
        """
        intake = await self._alcancavel(
            tenant_id, intake_id, actor_user_id=actor_user_id, actor_role=actor_role
        )

        # Revalidado no ato: entre abrir e aceitar pode ter passado uma semana.
        telefone = (
            await self._telefone_livre(tenant_id, intake.whatsapp_e164)
            if intake.whatsapp_e164
            else None
        )

        cliente = await self._customers.create_customer(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            legal_name=legal_name.strip() if legal_name else intake.legal_name,
            state_code=state_code or intake.state_code,
            trade_name=trade_name,
            document_number=document_number,
            # O titular é quem abriu, não quem aceitou. `create_customer` força o
            # próprio ator quando ele é `REPRESENTATIVE` — que é o caso de o
            # representante aceitar o seu — e respeita este valor para
            # `ADMIN`/`MANAGER`, que é o caso de a fila ser resolvida no
            # escritório.
            owner_user_id=intake.created_by_user_id,
            request_id=request_id,
        )
        await self._admin.flush()

        if telefone is not None:
            # É aqui que o acesso ao canal é criado: o contato entra no roster, o
            # Gateway espelha e passa a atender aquele número. Não passa pelo
            # `create_contact` porque o cliente acabou de nascer e ainda não está
            # visível ao `PortfolioScope` de um `MANAGER` — a checagem de escopo
            # de lá recusaria. As duas guardas que importam, canonização e
            # unicidade cruzada, já foram aplicadas em `_telefone_livre`.
            contato = CustomerContact(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                customer_id=cliente.id,
                name=(contact_name or intake.legal_name).strip()[:MAX_RAZAO_SOCIAL],
                whatsapp_e164=telefone,
                is_primary=True,
            )
            self._admin.add(contato)
            self._audit.record(
                action="CUSTOMER_CONTACT_CREATED",
                entity="customer_contacts",
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                entity_id=contato.id,
                after={
                    "customer_id": str(cliente.id),
                    "is_primary": True,
                    "from_intake_id": str(intake.id),
                },
                request_id=request_id,
            )

        intake.status = IntakeStatus.ACCEPTED
        intake.customer_id = cliente.id
        intake.resolved_at = datetime.now(UTC)
        intake.resolved_by_user_id = actor_user_id
        self._audit.record(
            action="CUSTOMER_INTAKE_ACCEPTED",
            entity="customer_intakes",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=intake.id,
            after={
                "customer_id": str(cliente.id),
                "owner_user_id": str(intake.created_by_user_id),
                "authorized_whatsapp": telefone is not None,
            },
            request_id=request_id,
        )
        await self._intakes.flush()
        return intake

    async def reject(
        self,
        tenant_id: uuid.UUID,
        intake_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
        reason: str,
        request_id: str | None = None,
    ) -> CustomerIntake:
        """Encerra sem criar cliente. O motivo é obrigatório.

        Rejeição sem motivo é indistinguível de engano seis meses depois — e quem
        abriu o pré-cadastro tem direito de saber por que ele não virou cliente.
        """
        intake = await self._alcancavel(
            tenant_id, intake_id, actor_user_id=actor_user_id, actor_role=actor_role
        )
        motivo = self._texto(reason, campo="motivo", maximo=MAX_MOTIVO)

        intake.status = IntakeStatus.REJECTED
        intake.rejected_reason = motivo
        intake.resolved_at = datetime.now(UTC)
        intake.resolved_by_user_id = actor_user_id
        self._audit.record(
            action="CUSTOMER_INTAKE_REJECTED",
            entity="customer_intakes",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=intake.id,
            after={"reason": motivo},
            request_id=request_id,
        )
        await self._intakes.flush()
        return intake

    # ------------------------------------------------------------------ fila

    async def queue(
        self,
        scope: PortfolioScope,
        *,
        actor_role: UserRole,
        status: IntakeStatus | None = IntakeStatus.PENDING,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[CustomerIntake, object]], int]:
        """Fila de pré-cadastros, recortada pelo papel.

        `ADMIN` e `MANAGER` veem o tenant inteiro, como no portal. O
        `REPRESENTATIVE` vê apenas os que abriu.
        """
        autor = scope.owner_user_id if actor_role is UserRole.REPRESENTATIVE else None
        linhas = await self._intakes.list(
            scope.tenant_id,
            author_user_id=autor,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await self._intakes.count(
            scope.tenant_id, author_user_id=autor, status=status
        )
        return linhas, total
