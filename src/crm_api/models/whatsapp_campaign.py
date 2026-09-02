"""Projeção comercial de campanhas de WhatsApp (F6.1, ADR-028).

O CRM não é dono do canal: `messages`, consentimento, opt-out e os estados
operacionais continuam no Gateway. O que mora aqui é o agregado comercial que
permite autorizar, auditar, listar campanhas e levá-las à ficha do cliente —
e, nesta fase, **nada dispara**: não existe código de envio, nem chamada ao
Gateway ou à Meta.

O conceito central é a fotografia. Critérios, público, template, variáveis e
confirmação são snapshots: eles explicam o que foi revisado e aprovado naquele
dia, mesmo que carteira, grupo ou contato mudem depois. Por isso não há método
de atualização desses campos em serviço nenhum — corrigir uma campanha é
cancelar o rascunho e criar outro, nunca reescrever o que alguém já revisou.

Os identificadores `gateway_*` nascem nulos de propósito: são o lugar reservado
para a correlação com o Gateway quando o contrato da F6.4 existir. Reservar a
coluna agora custa nada; descobrir na integração que a chave não tem onde morar
custaria uma migração sobre dados vivos.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base

# Importados pelas chaves estrangeiras, não pelo uso direto — a mesma garantia
# do `customer_intake`: sem as tabelas referenciadas no `MetaData`, o DDL das
# colunas `tenant_id`, `customer_id`, `contact_id` e afins não resolve.
from crm_api.models.customer import Customer, Tenant  # noqa: F401
from crm_api.models.customer_contact import CustomerContact  # noqa: F401
from crm_api.models.interaction import CustomerInteraction  # noqa: F401
from crm_api.models.user import User  # noqa: F401

_JSON_COLUMN = JSON().with_variant(JSONB(), "postgresql")


class CampaignStatus(StrEnum):
    """Estado **comercial** da campanha, não estado técnico de mensagem.

    Enum no banco pela regra da casa (`0008`/`0011`): o conjunto é fechado por
    natureza — as transições fazem parte do contrato com o Gateway — e os
    `CHECK` abaixo amarram estados a campos, então um estado novo exigiria
    migração de qualquer maneira.
    """

    DRAFT = "DRAFT"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class RecipientStatus(StrEnum):
    """Estado projetado de cada destinatário.

    `PENDING`→`SENT`→`DELIVERED`→`READ` e `FAILED` são projeções dos eventos
    que o Gateway emitirá na F6.4. `EXCLUDED` é decisão registrada na prévia —
    sem consentimento, sem contato elegível — e nunca transiciona para envio.
    """

    PENDING = "PENDING"
    EXCLUDED = "EXCLUDED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"


class WhatsappCampaign(Base):
    __tablename__ = "whatsapp_campaigns"
    __table_args__ = (
        # Reentrega do mesmo comando de criação não abre segunda campanha.
        # A chave vem de quem cria (portal ou, no futuro, o Gateway); quem
        # decide a corrida é o banco, como em `customer_intakes`.
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="ux_whatsapp_campaigns_idempotency"
        ),
        # Rascunho não tem confirmação nem correlação externa; confirmada em
        # diante carrega a confirmação que a autorizou. `CANCELLED` admite os
        # dois formatos porque se cancela tanto um rascunho quanto pendências
        # de uma campanha já confirmada.
        CheckConstraint(
            "(status IN ('DRAFT', 'AWAITING_CONFIRMATION')"
            " AND confirmation IS NULL AND gateway_campaign_id IS NULL)"
            " OR (status IN ('CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'FAILED')"
            " AND confirmation IS NOT NULL)"
            " OR (status = 'CANCELLED')",
            name="ck_whatsapp_campaigns_confirmation",
        ),
        # Índice parcial: unicidade da correlação externa só quando ela existe.
        Index(
            "ux_whatsapp_campaigns_gateway",
            "tenant_id",
            "gateway_campaign_id",
            unique=True,
            sqlite_where=text("gateway_campaign_id IS NOT NULL"),
            postgresql_where=text("gateway_campaign_id IS NOT NULL"),
        ),
        Index("ix_whatsapp_campaigns_tenant", "tenant_id", "status", "created_at"),
        Index(
            "ix_whatsapp_campaigns_representative",
            "representative_user_id",
            "created_at",
        ),
    )

    # Sem `index=True` em `tenant_id` e `status`: o composto acima já os cobre
    # como colunas iniciais, e o atalho criaria no modelo dois índices que a
    # `0015` não cria — a divergência que `ops/ci/check_pg_schema.py` existe
    # para não deixar nascer.
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # Responsável comercial exibido e **congelado**: transferir a carteira
    # depois não transfere a campanha. Nulável no modelo-alvo; hoje o serviço
    # sempre o preenche com o ator, porque a alçada de criar em nome de outra
    # carteira é pendência da F6.0.
    representative_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))

    status: Mapped[CampaignStatus] = mapped_column(
        SqlEnum(CampaignStatus, name="whatsapp_campaign_status"),
        default=CampaignStatus.DRAFT,
    )

    # As fotografias. Imutáveis por contrato de serviço — nenhum método as
    # reescreve — e o que foi aprovado permanece explicável mesmo se o cadastro
    # mudar depois.
    criteria_snapshot: Mapped[dict] = mapped_column(_JSON_COLUMN)
    audience_summary_snapshot: Mapped[dict] = mapped_column(_JSON_COLUMN)
    template_snapshot: Mapped[dict] = mapped_column(_JSON_COLUMN)
    variables_snapshot: Mapped[dict | None] = mapped_column(_JSON_COLUMN, nullable=True)
    # Ator, momento, canal e chave idempotente da confirmação — preenchida
    # apenas pelo fluxo de confirmação (F6.3/F6.4), nunca na criação.
    confirmation: Mapped[dict | None] = mapped_column(_JSON_COLUMN, nullable=True)

    # Correlação com o Gateway, reservada para a F6.4.
    gateway_campaign_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    gateway_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    gateway_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WhatsappCampaignRecipient(Base):
    """Fotografia de cada alvo revisado.

    Liga campanha → cliente → contato → representante e permite que a ficha do
    cliente encontre a campanha sem consultar o Gateway. Um cliente pode ter
    mais de um contato; a unicidade é por contato quando ele existe e por
    cliente quando a linha registra exclusão sem contato elegível — os dois
    índices parciais abaixo, porque um `UNIQUE` com coluna nula não deduplica
    no PostgreSQL.
    """

    __tablename__ = "whatsapp_campaign_recipients"
    __table_args__ = (
        # Exclusão tem motivo; quem não foi excluído não carrega motivo — o
        # banco recusa a combinação que a tela não sabe apresentar.
        CheckConstraint(
            "(status = 'EXCLUDED' AND excluded_reason IS NOT NULL)"
            " OR (status <> 'EXCLUDED' AND excluded_reason IS NULL)",
            name="ck_wcr_exclusion",
        ),
        # Sem contato só se excluído: um destinatário elegível sem telefone não
        # existe — seria uma linha que promete envio impossível.
        CheckConstraint(
            "contact_id IS NOT NULL OR status = 'EXCLUDED'",
            name="ck_wcr_contact",
        ),
        CheckConstraint(
            "failure_reason IS NULL OR status = 'FAILED'",
            name="ck_wcr_failure",
        ),
        Index(
            "ux_wcr_contact",
            "campaign_id",
            "customer_id",
            "contact_id",
            unique=True,
            sqlite_where=text("contact_id IS NOT NULL"),
            postgresql_where=text("contact_id IS NOT NULL"),
        ),
        Index(
            "ux_wcr_customer_without_contact",
            "campaign_id",
            "customer_id",
            unique=True,
            sqlite_where=text("contact_id IS NULL"),
            postgresql_where=text("contact_id IS NULL"),
        ),
        # Idempotência de evento por mensagem externa, reservada para a F6.4.
        Index(
            "ux_wcr_gateway_message",
            "tenant_id",
            "gateway_message_id",
            unique=True,
            sqlite_where=text("gateway_message_id IS NOT NULL"),
            postgresql_where=text("gateway_message_id IS NOT NULL"),
        ),
        # A ficha do cliente lista "de quais campanhas participei".
        Index("ix_wcr_customer", "customer_id", "created_at"),
        # Declarado com o nome que a `0015` cria, em vez de sair do atalho
        # `index=True` — que geraria `ix_..._campaign_id` e faria modelo e
        # migração divergirem no nome.
        Index("ix_whatsapp_campaign_recipients_campaign", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_campaigns.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_contacts.id"), nullable=True
    )
    # Titular na hora da prévia, congelado — como o responsável da campanha.
    representative_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Dados mínimos para a tela de revisão explicar quem é a linha sem
    # depender do cadastro vivo. Não substitui o contato mestre.
    recipient_snapshot: Mapped[dict] = mapped_column(_JSON_COLUMN)

    status: Mapped[RecipientStatus] = mapped_column(
        SqlEnum(RecipientStatus, name="whatsapp_campaign_recipient_status"),
        default=RecipientStatus.PENDING,
    )
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reservados para a F6.4: identificador da mensagem no Gateway e a
    # interação projetada quando o cliente responder.
    gateway_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_interactions.id"), nullable=True
    )

    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
