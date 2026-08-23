"""Conversa entre representante e cliente, registrada à mão na ficha.

A `0010` fixou que uma interação tem **exatamente um** dono: ou o cliente, ou o
usuário do portal. A regra estava certa para o caso que ela tratava — a conversa
do representante com o robô, em que "bom dia" não pertence a cliente nenhum.

Mas representante conversando com o **cliente** é uma terceira forma, e ela tem
os dois donos. O `ck_interaction_exactly_one_owner` recusava exatamente a linha
que a ficha precisa gravar.

A saída não é afrouxar o `CHECK` para "pelo menos um dono": isso devolveria a
permissividade que a `0010` tirou. Entra um discriminador, `kind`, e o `CHECK`
passa a exigir de cada forma o seu formato exato — a mesma disciplina do
`ck_intake_resolution` da `0011`, que amarra cada estado aos seus campos.

Três mudanças acompanham:

- `direction` passa a ser nulável, exigida só das formas de canal. Uma ligação é
  feita ou recebida; "visitei o cliente" não é nem uma nem outra, e forçar a
  escolha produziria dado inventado.
- `edited_at` permite exibir a marca de edição sem consultar `audit_log`.
- O `CHECK` antigo sai, substituído pelos dois novos.

**Nenhuma linha existente muda de dono.** O backfill deriva `kind` do que já
está lá: quem tem `customer_id` vira `CUSTOMER_CHANNEL`, quem tem
`actor_user_id` vira `ACTOR_CHANNEL`. Como o `CHECK` da `0010` garantia que todo
registro tem exatamente um dos dois, a derivação é total — não sobra linha.

Revision ID: 0012_representative_notes
Revises: 0011_customer_intakes
Create Date: 2026-08-22
"""

from alembic import op

revision = "0012_representative_notes"
down_revision = "0011_customer_intakes"
branch_labels = None
depends_on = None

_UPGRADE = (
    "CREATE TYPE interaction_kind AS ENUM "
    "('CUSTOMER_CHANNEL', 'ACTOR_CHANNEL', 'REPRESENTATIVE_NOTE')",
    # Sem DEFAULT: a coluna nasce nula, o backfill preenche e só então ela vira
    # NOT NULL. Um DEFAULT aqui esconderia uma linha que o backfill não cobriu.
    "ALTER TABLE customer_interactions ADD COLUMN kind interaction_kind",
    "ALTER TABLE customer_interactions ADD COLUMN edited_at timestamptz",
    """
    UPDATE customer_interactions
       SET kind = CASE
                    WHEN customer_id IS NOT NULL THEN 'CUSTOMER_CHANNEL'
                    ELSE 'ACTOR_CHANNEL'
                  END::interaction_kind
     WHERE kind IS NULL
    """,
    """
    DO $$
    DECLARE
      orfas bigint;
    BEGIN
      SELECT count(*) INTO orfas FROM customer_interactions WHERE kind IS NULL;
      IF orfas > 0 THEN
        RAISE EXCEPTION
          '% interacoes ficaram sem kind; o CHECK da 0010 deveria ter impedido isso',
          orfas;
      END IF;
    END $$
    """,
    "ALTER TABLE customer_interactions ALTER COLUMN kind SET NOT NULL",
    "ALTER TABLE customer_interactions ALTER COLUMN direction DROP NOT NULL",
    "ALTER TABLE customer_interactions DROP CONSTRAINT ck_interaction_exactly_one_owner",
    "ALTER TABLE customer_interactions ADD CONSTRAINT ck_interaction_owner_by_kind "
    "CHECK ((kind = 'CUSTOMER_CHANNEL'"
    " AND customer_id IS NOT NULL AND actor_user_id IS NULL)"
    " OR (kind = 'ACTOR_CHANNEL'"
    " AND customer_id IS NULL AND actor_user_id IS NOT NULL)"
    " OR (kind = 'REPRESENTATIVE_NOTE'"
    " AND customer_id IS NOT NULL AND actor_user_id IS NOT NULL))",
    "ALTER TABLE customer_interactions ADD CONSTRAINT ck_interaction_channel_has_direction "
    "CHECK (kind = 'REPRESENTATIVE_NOTE' OR direction IS NOT NULL)",
)

# Reverter apaga a forma que só existe aqui. Como na `0010`, falhar é o
# comportamento correto: voltar ao `CHECK` de dono único com notas gravadas
# derrubaria a restrição, e apagá-las em silêncio seria pior — a nota é a única
# fonte daquele registro, não uma projeção que o Gateway sabe reenviar.
_DOWNGRADE = (
    """
    DO $$
    DECLARE
      notas bigint;
    BEGIN
      SELECT count(*) INTO notas
        FROM customer_interactions
       WHERE kind = 'REPRESENTATIVE_NOTE';
      IF notas > 0 THEN
        RAISE EXCEPTION
          'ha % notas de representante; elas nao existem em outro lugar, '
          'decida o destino delas antes de reverter',
          notas;
      END IF;
    END $$
    """,
    "ALTER TABLE customer_interactions DROP CONSTRAINT ck_interaction_channel_has_direction",
    "ALTER TABLE customer_interactions DROP CONSTRAINT ck_interaction_owner_by_kind",
    # Só é seguro por causa da guarda acima: sem notas, toda linha restante é de
    # canal e tem `direction` preenchida.
    "ALTER TABLE customer_interactions ALTER COLUMN direction SET NOT NULL",
    "ALTER TABLE customer_interactions ADD CONSTRAINT ck_interaction_exactly_one_owner "
    "CHECK ((customer_id IS NOT NULL AND actor_user_id IS NULL) "
    "OR (customer_id IS NULL AND actor_user_id IS NOT NULL))",
    "ALTER TABLE customer_interactions DROP COLUMN edited_at",
    "ALTER TABLE customer_interactions DROP COLUMN kind",
    "DROP TYPE interaction_kind",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
