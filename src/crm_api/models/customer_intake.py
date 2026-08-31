"""Pré-cadastro de cliente aberto pelo representante (W7).

Tabela separada, e não `customers` com marca de rascunho, pelo motivo do ADR-020:
o rascunho mora onde o consumidor de produção não lê. Um `customers` inativo
entraria em toda consulta que filtra por `active` e passaria a significar duas
coisas — "desativado" e "ainda não existe".

E há uma consequência que essa separação compra de graça: **intake pendente não
toca o roster**. Não existe `customer_contacts` até alguém aceitar no portal.
Criar um contato de WhatsApp é criar acesso ao canal — o contato entra no roster,
o Gateway espelha e passa a atender aquele número. Se a mensagem gravasse o
contato direto, uma frase no WhatsApp autorizaria um telefone qualquer a
conversar com o CRM.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from crm_api.models.base import Base

# Importados pelas chaves estrangeiras, não pelo uso direto: sem as tabelas
# referenciadas no `MetaData`, o tipo das colunas `tenant_id`, `created_by_user_id`
# e `customer_id` não resolve e o DDL falha. Hoje funciona por ordem de import de
# outro módulo, o que é acidente — este `import` o torna garantia.
from crm_api.models.customer import Customer, Tenant  # noqa: F401
from crm_api.models.user import User  # noqa: F401


class IntakeStatus(StrEnum):
    """Enum no banco, e não texto com `CHECK`.

    A regra da casa (`0008`) é enum quando o conjunto é fechado por natureza e
    texto quando ele deve crescer sem migração. Aqui o `CHECK` de resolução
    enumera os três estados para amarrar cada um aos seus campos, então um estado
    novo exigiria migração de qualquer maneira — e o enum ainda dá o erro no
    lugar certo.
    """

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class IntakeSource(StrEnum):
    """Texto, como o `channel` da `0008`: uma segunda origem — formulário no
    site, importação — não deve exigir migração."""

    WHATSAPP = "WHATSAPP"


class CustomerIntake(Base):
    __tablename__ = "customer_intakes"
    __table_args__ = (
        # A chave de idempotência é o `wamid` da mensagem confirmada. O Gateway
        # reentrega webhook, e sem isto uma reentrega abriria dois pré-cadastros
        # do mesmo cliente — que alguém depois aceitaria duas vezes.
        UniqueConstraint("tenant_id", "idempotency_key", name="ux_customer_intakes_idempotency"),
        # Resolvido é resolvido: aceito aponta para o cliente criado, rejeitado
        # carrega o motivo, e pendente não tem nem um nem outro. O banco recusa
        # as combinações que a tela não sabe apresentar.
        CheckConstraint(
            "(status = 'PENDING' AND customer_id IS NULL AND rejected_reason IS NULL"
            " AND resolved_at IS NULL AND resolved_by_user_id IS NULL)"
            " OR (status = 'ACCEPTED' AND customer_id IS NOT NULL AND rejected_reason IS NULL"
            " AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)"
            " OR (status = 'REJECTED' AND customer_id IS NULL AND rejected_reason IS NOT NULL"
            " AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)",
            name="ck_customer_intakes_resolution",
        ),
        Index("ix_customer_intakes_pending", "tenant_id", "status", "created_at"),
        Index("ix_customer_intakes_author", "created_by_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    # O representante, resolvido pelo ator do manifesto — nunca informado no
    # corpo da requisição. Quem escreveu é o telefone que assinou a mensagem.
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(16), default=IntakeSource.WHATSAPP.value)
    idempotency_key: Mapped[str] = mapped_column(String(128))

    legal_name: Mapped[str] = mapped_column(Text)
    # Obrigatória: sem UF não há regra de ICMS, e o R4 falha de propósito em vez
    # de estimar. Pedir na conversa custa menos que descobrir a falta na hora de
    # gerar a lista.
    state_code: Mapped[str] = mapped_column(CHAR(2))
    whatsapp_e164: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Texto do representante, **não** SKU. Casar "75/36 urdume" com um artigo é
    # decisão comercial; o ADR-021 registra o que custa amarrar histórico de
    # preço ao artigo errado. A resolução acontece no portal, pelo combobox.
    preferred_products_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[IntakeStatus] = mapped_column(
        SqlEnum(IntakeStatus, name="customer_intake_status"),
        default=IntakeStatus.PENDING,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
