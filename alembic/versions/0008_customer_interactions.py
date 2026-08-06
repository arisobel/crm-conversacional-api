"""Projeção do histórico de interações do cliente.

R5 da direção de CRM de representantes. Ver ADR-016: o CRM não é dono da
conversa — `conversations` e `messages` permanecem no Gateway. Esta tabela é uma
projeção alimentada por push, feita para responder "o que aconteceu com este
cliente" sem que o portal precise consultar o Gateway a cada abertura de ficha.

`channel` é texto, e não enum: acrescentar e-mail ou telefone como canal não
deve exigir migração. `direction` é enum porque só existem duas direções e a
consulta filtra por elas.

A unicidade por `(tenant_id, source, external_ref)` é o que torna o push
reentrante: o Gateway pode reenviar o mesmo evento à vontade sem duplicar a
linha do tempo.

Revision ID: 0008_customer_interactions
Revises: 0007_icms_rules
Create Date: 2026-08-06
"""

from alembic import op

revision = "0008_customer_interactions"
down_revision = "0007_icms_rules"
branch_labels = None
depends_on = None

_UPGRADE = (
    "CREATE TYPE interaction_direction AS ENUM ('INBOUND', 'OUTBOUND')",
    """
    CREATE TABLE customer_interactions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      customer_id uuid NOT NULL REFERENCES customers(id),
      -- Nulo quando o evento não veio de um contato identificado, como uma
      -- anotação registrada pelo próprio representante.
      contact_id uuid REFERENCES customer_contacts(id),
      channel text NOT NULL DEFAULT 'WHATSAPP',
      direction interaction_direction NOT NULL,
      source text NOT NULL,
      external_ref text NOT NULL,
      occurred_at timestamptz NOT NULL,
      summary text,
      payload jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT ux_interaction_source_ref UNIQUE (tenant_id, source, external_ref)
    )
    """,
    "CREATE INDEX ix_customer_interactions_timeline "
    "ON customer_interactions(customer_id, occurred_at DESC)",
    # O expurgo por retenção varre por data dentro do tenant.
    "CREATE INDEX ix_customer_interactions_occurred "
    "ON customer_interactions(tenant_id, occurred_at)",
)

_DOWNGRADE = (
    "DROP TABLE customer_interactions",
    "DROP TYPE interaction_direction",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
