"""Pré-cadastro de cliente aberto pelo representante.

W7 do [manifesto por ator](../../docs/30_architecture/WHATSAPP_ACTOR_MANIFEST.md).

Tabela nova, nada existente é alterado — o que torna esta a migração mais barata
da série: não há dado a canonizar, nenhuma coluna muda de tipo e a reversão é um
`DROP` limpo enquanto ninguém tiver aceitado um pré-cadastro.

Duas guardas moram no banco de propósito, e não só no serviço:

`ux_customer_intakes_idempotency` — a chave é o `wamid` da mensagem confirmada. O
Gateway reentrega webhook; sem unicidade no banco, duas entregas concorrentes
passariam pela checagem do serviço nas duas e abririam dois pré-cadastros do
mesmo cliente.

`ck_customer_intakes_resolution` — amarra cada estado aos seus campos. Aceito tem
cliente e não tem motivo; rejeitado tem motivo e não tem cliente; pendente não
tem nem um nem outro nem quem resolveu. As combinações que a tela do portal não
sabe apresentar o banco recusa.

Revision ID: 0011_customer_intakes
Revises: 0010_representative_interactions
Create Date: 2026-08-17
"""

from alembic import op

revision = "0011_customer_intakes"
down_revision = "0010_representative_interactions"
branch_labels = None
depends_on = None

_UPGRADE = (
    "CREATE TYPE customer_intake_status AS ENUM ('PENDING', 'ACCEPTED', 'REJECTED')",
    """
    CREATE TABLE customer_intakes (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      created_by_user_id uuid NOT NULL REFERENCES users(id),
      source text NOT NULL DEFAULT 'WHATSAPP',
      idempotency_key text NOT NULL,
      legal_name text NOT NULL CHECK (btrim(legal_name) <> ''),
      state_code char(2) NOT NULL CHECK (state_code ~ '^[A-Z][A-Z]$'),
      whatsapp_e164 text CHECK (whatsapp_e164 ~ '^\\+[1-9][0-9]{7,14}$'),
      preferred_products_text text,
      status customer_intake_status NOT NULL DEFAULT 'PENDING',
      customer_id uuid REFERENCES customers(id),
      rejected_reason text,
      created_at timestamptz NOT NULL DEFAULT now(),
      resolved_at timestamptz,
      resolved_by_user_id uuid REFERENCES users(id),
      CONSTRAINT ck_customer_intakes_resolution CHECK (
        (status = 'PENDING' AND customer_id IS NULL AND rejected_reason IS NULL
         AND resolved_at IS NULL AND resolved_by_user_id IS NULL)
        OR (status = 'ACCEPTED' AND customer_id IS NOT NULL AND rejected_reason IS NULL
            AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)
        OR (status = 'REJECTED' AND customer_id IS NULL AND rejected_reason IS NOT NULL
            AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL)
      )
    )
    """,
    "CREATE UNIQUE INDEX ux_customer_intakes_idempotency"
    " ON customer_intakes(tenant_id, idempotency_key)",
    "CREATE INDEX ix_customer_intakes_pending"
    " ON customer_intakes(tenant_id, status, created_at DESC)",
    "CREATE INDEX ix_customer_intakes_author"
    " ON customer_intakes(created_by_user_id, created_at DESC)",
)

# A reversão recusa apagar pré-cadastro já aceito: aquele intake é a única prova
# de origem do cliente que existe hoje na base. Rejeitado e pendente somem sem
# perda — nenhum outro registro aponta para eles.
_DOWNGRADE = (
    """
    DO $$
    DECLARE
      aceitos bigint;
    BEGIN
      SELECT count(*) INTO aceitos FROM customer_intakes WHERE status = 'ACCEPTED';
      IF aceitos > 0 THEN
        RAISE EXCEPTION
          'ha % pre-cadastros aceitos; apagar a tabela perderia a origem desses clientes',
          aceitos;
      END IF;
    END $$
    """,
    "DROP TABLE customer_intakes",
    "DROP TYPE customer_intake_status",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
