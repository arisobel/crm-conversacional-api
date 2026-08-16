"""Conversa de representante como histórico dele, não da ficha de um cliente.

W4 do [manifesto por ator](../../docs/30_architecture/WHATSAPP_ACTOR_MANIFEST.md),
decidida no ADR-022.

O Gateway empurra toda mensagem de quem ele atende. Hoje `POST
/internal/interactions` resolve o evento pelo contato E.164 e recusa o que não
encontra cliente — então, no instante em que o primeiro número de representante
for autorizado no painel do Gateway, cada mensagem dele viraria um evento
recusado e sumiria.

`customer_id` passa a ser nulável e ganha um par exclusivo, `actor_user_id`. O
`CHECK` recusa qualquer outra combinação: sem dono, ou com dois. Atribuir a
conversa do representante ao cliente que ele consultou foi recusado porque
"bom dia" não teria a que se ligar, e porque misturaria na ficha dois assuntos
que a tela apresenta como um só.

Nenhuma linha existente muda: todas já têm `customer_id` e ficam com
`actor_user_id` nulo, que é exatamente o que o `CHECK` exige delas.

Revision ID: 0010_representative_interactions
Revises: 0009_whatsapp_actor_identity
Create Date: 2026-08-16
"""

from alembic import op

revision = "0010_representative_interactions"
down_revision = "0009_whatsapp_actor_identity"
branch_labels = None
depends_on = None

_UPGRADE = (
    "ALTER TABLE customer_interactions ALTER COLUMN customer_id DROP NOT NULL",
    "ALTER TABLE customer_interactions ADD COLUMN actor_user_id uuid REFERENCES users(id)",
    "ALTER TABLE customer_interactions ADD CONSTRAINT ck_interaction_exactly_one_owner "
    "CHECK ((customer_id IS NOT NULL AND actor_user_id IS NULL) "
    "OR (customer_id IS NULL AND actor_user_id IS NOT NULL))",
    "CREATE INDEX ix_customer_interactions_actor "
    "ON customer_interactions(actor_user_id, occurred_at DESC)",
)

# A reversão só é possível enquanto não houver conversa de representante
# gravada: voltar `customer_id` a `NOT NULL` com linhas de ator apagaria o dono
# delas em silêncio. Falhar aqui é o comportamento correto — quem reverter
# precisa decidir o que fazer com esse histórico.
_DOWNGRADE = (
    """
    DO $$
    DECLARE
      pendentes bigint;
    BEGIN
      SELECT count(*) INTO pendentes
        FROM customer_interactions
       WHERE actor_user_id IS NOT NULL;
      IF pendentes > 0 THEN
        RAISE EXCEPTION
          'ha % interacoes de representante; decida o destino delas antes de reverter',
          pendentes;
      END IF;
    END $$
    """,
    "DROP INDEX ix_customer_interactions_actor",
    "ALTER TABLE customer_interactions DROP CONSTRAINT ck_interaction_exactly_one_owner",
    "ALTER TABLE customer_interactions DROP COLUMN actor_user_id",
    "ALTER TABLE customer_interactions ALTER COLUMN customer_id SET NOT NULL",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
