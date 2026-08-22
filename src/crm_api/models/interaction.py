import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base

_JSON_COLUMN = JSON().with_variant(JSONB(), "postgresql")

WHATSAPP_CHANNEL = "WHATSAPP"
GATEWAY_SOURCE = "whatsapp-gateway"

# Nota registrada na ficha não vem de canal nenhum: ela nasce no portal, e é o
# próprio portal que responde por ela.
PORTAL_SOURCE = "portal"

# Meios que o representante escolhe ao registrar a nota. `channel` continua
# sendo texto livre no banco porque o Gateway grava o dele sem consultar esta
# lista; a validação vale para o que entra pelo portal.
NOTE_CHANNELS = ("PHONE", "VISIT", "WHATSAPP", "EMAIL", "OTHER")


class InteractionDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class InteractionKind(StrEnum):
    """Qual das três formas esta linha é.

    O discriminador existe porque as três têm **donos diferentes**, e um
    `CHECK` único não conseguia exigir o formato certo de cada uma sem afrouxar
    para "pelo menos um dono" — que é justamente o que a `0010` queria barrar.
    """

    # Cliente conversando com o robô. Dono: o cliente.
    CUSTOMER_CHANNEL = "CUSTOMER_CHANNEL"
    # Representante conversando com o robô. Dono: ele mesmo. "Bom dia" dito ao
    # robô não pertence a cliente nenhum — é o caso que a `0010` protegeu.
    ACTOR_CHANNEL = "ACTOR_CHANNEL"
    # Representante e cliente conversando entre si, registrado à mão na ficha.
    # Tem os dois donos, e é a forma que o `CHECK` da `0010` recusava.
    REPRESENTATIVE_NOTE = "REPRESENTATIVE_NOTE"


class CustomerInteraction(Base):
    """Uma linha da história de um cliente **ou de um representante**.

    O CRM não é dono da conversa (ADR-016): a origem continua sendo o Gateway, e
    esta tabela guarda apenas o suficiente para montar a linha do tempo da ficha
    sem consultá-lo. Nunca sofre `UPDATE` — reprocessar o mesmo evento é
    reconhecido pela unicidade de `(tenant_id, source, external_ref)` e
    descartado, não regravado.

    `kind` diz qual das três formas a linha é, e o banco exige de cada uma o seu
    formato exato de dono. Conversa de representante **com o robô** é histórico
    dele: atribuí-la ao cliente que ele consultou deixaria "bom dia" sem dono.
    Conversa de representante **com o cliente** tem os dois donos, naturalmente,
    e é a forma que a `0012` acrescentou.

    Linhas de canal nunca sofrem `UPDATE`: o evento aconteceu, é fato. A nota
    manual é a exceção deliberada — é texto que uma pessoa escreveu, e proibir
    corrigir só faria nascer uma segunda nota dizendo "corrigindo a anterior".
    Cada edição grava em `audit_log` e carimba `edited_at`.
    """

    __tablename__ = "customer_interactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "external_ref", name="ux_interaction_source_ref"),
        Index("ix_customer_interactions_timeline", "customer_id", "occurred_at"),
        Index("ix_customer_interactions_occurred", "tenant_id", "occurred_at"),
        Index("ix_customer_interactions_actor", "actor_user_id", "occurred_at"),
        CheckConstraint(
            "(kind = 'CUSTOMER_CHANNEL'"
            " AND customer_id IS NOT NULL AND actor_user_id IS NULL)"
            " OR (kind = 'ACTOR_CHANNEL'"
            " AND customer_id IS NULL AND actor_user_id IS NOT NULL)"
            " OR (kind = 'REPRESENTATIVE_NOTE'"
            " AND customer_id IS NOT NULL AND actor_user_id IS NOT NULL)",
            name="ck_interaction_owner_by_kind",
        ),
        # Evento de canal sempre tem sentido; nota nem sempre. Uma ligação é
        # feita ou recebida, mas "visitei o cliente" não é nem uma nem outra, e
        # forçar a escolha produziria dado inventado.
        CheckConstraint(
            "kind = 'REPRESENTATIVE_NOTE' OR direction IS NOT NULL",
            name="ck_interaction_channel_has_direction",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    # Preenchido quando quem falou é um usuário do portal — hoje só o
    # representante, já que nenhuma alçada administrativa passa pelo canal.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_contacts.id"), nullable=True
    )
    kind: Mapped[InteractionKind] = mapped_column(
        SqlEnum(InteractionKind, name="interaction_kind"),
        default=InteractionKind.CUSTOMER_CHANNEL,
    )
    channel: Mapped[str] = mapped_column(Text, default=WHATSAPP_CHANNEL)
    direction: Mapped[InteractionDirection | None] = mapped_column(
        SqlEnum(InteractionDirection, name="interaction_direction"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text)
    external_ref: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(_JSON_COLUMN, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Só nota manual chega a ter valor aqui. Nulo significa "nunca editada", e é
    # o que a timeline usa para exibir a marca sem consultar `audit_log`.
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
