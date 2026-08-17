"""Identidade do ator no WhatsApp: telefone canônico e apelido público.

Primeira etapa do [manifesto por ator](../../docs/30_architecture/WHATSAPP_ACTOR_MANIFEST.md).

Duas coisas, pelo mesmo motivo — as duas são pré-requisito para o CRM
reconhecer quem está falando:

**Os telefones passam a ser canônicos.** `users.whatsapp_e164` existia desde a
`0003`, validado apenas por formato: `+551188887777` era aceito e jamais casaria
com o `+5511988887777` que chega da Meta. `customer_contacts.whatsapp_e164` é
normalizado na borda desde a R2, mas **nunca foi corrigido para trás** — linha
criada antes dela pode estar em qualquer das duas grafias, e nesse caso já não
casa com mensagem nenhuma hoje.

Os `UPDATE` abaixo aplicam o nono dígito nas duas tabelas, e o índice parcial
impede que dois usuários do mesmo tenant fiquem com o mesmo número.

**`public_ref`** é o identificador opaco que o Gateway exige no `actor.id`, com
o formato `^[a-f0-9]{24}$` que o validador dele impõe. É sorteado e guardado,
não derivado de segredo: derivar amarraria a identidade do ator à rotação da
chave, e girar a chave mudaria todos os identificadores de uma vez.

A migração **para** se encontrar colisão entre `users` e `customer_contacts`.
Um telefone que seja os dois receberia capacidades de representante por um
cadastro descuidado, e escolher um dos lados aqui seria decidir em silêncio uma
questão que é comercial.

Revision ID: 0009_whatsapp_actor_identity
Revises: 0008_customer_interactions
Create Date: 2026-08-16
"""

from alembic import op

revision = "0009_whatsapp_actor_identity"
down_revision = "0008_customer_interactions"
branch_labels = None
depends_on = None

# O nono dígito só vale para celular brasileiro: `+55`, DDD de 11 a 99 e oito
# dígitos começando em 6-9. Fixo começa em 2-5 e fica intacto; fora do `+55`
# nada é inferido.
_ANTIGO = "^\\+55[1-9][0-9][6-9][0-9]{7}$"
_COM_NONO = (
    "'+55' || substring({t}.whatsapp_e164 from 4 for 2) || '9'"
    " || substring({t}.whatsapp_e164 from 6)"
)


def _canonicalize(table: str) -> str:
    return f"""
    UPDATE {table}
       SET whatsapp_e164 = {_COM_NONO.format(t=table)}
     WHERE whatsapp_e164 ~ '{_ANTIGO}'
    """


def _assert_no_self_collision(table: str, label: str) -> str:
    """Duas linhas da mesma tabela que viram o mesmo número ao canonizar.

    Sem esta checagem, o `UPDATE` seguinte estouraria a unicidade com o erro
    cru do banco, sem dizer quais linhas nem por quê. São o mesmo assinante
    cadastrado duas vezes, e fundir os dois cadastros é decisão comercial.
    """
    return f"""
    DO $$
    DECLARE
      duplicados text;
    BEGIN
      -- Duas camadas de agregação de propósito: a de dentro acha cada grupo
      -- repetido, a de fora junta todos numa mensagem só. Reportar um por vez
      -- faria quem corrige descobrir o próximo a cada nova tentativa de deploy.
      SELECT string_agg(canonico, ', ') INTO duplicados
        FROM (
          SELECT canonico
            FROM (
              SELECT tenant_id,
                     CASE WHEN whatsapp_e164 ~ '{_ANTIGO}'
                          THEN {_COM_NONO.format(t=table)}
                          ELSE whatsapp_e164 END AS canonico
                FROM {table}
               WHERE whatsapp_e164 IS NOT NULL
            ) AS normalizado
           GROUP BY tenant_id, canonico
          HAVING count(*) > 1
        ) AS repetidos;
      IF duplicados IS NOT NULL THEN
        RAISE EXCEPTION
          'mesmo assinante cadastrado duas vezes em {label}: %', duplicados;
      END IF;
    END $$
    """

_ASSERT_NO_COLLISION = """
DO $$
DECLARE
  colliding text;
BEGIN
  SELECT string_agg(u.whatsapp_e164, ', ')
    INTO colliding
    FROM users u
    JOIN customer_contacts c
      ON c.tenant_id = u.tenant_id
     AND c.whatsapp_e164 = u.whatsapp_e164;
  IF colliding IS NOT NULL THEN
    RAISE EXCEPTION
      'telefone e usuario do portal e contato de cliente ao mesmo tempo: %', colliding;
  END IF;
END $$
"""

_UPGRADE = (
    # A ordem é a checagem: canonizar as duas tabelas **antes** de comparar uma
    # com a outra. Um contato gravado sem o nono dígito e um usuário com ele são
    # o mesmo assinante, e comparar as grafias cruas deixaria a colisão passar —
    # para depois o resolvedor tratar aquele cliente como representante.
    _assert_no_self_collision("customer_contacts", "customer_contacts"),
    _assert_no_self_collision("users", "users"),
    _canonicalize("customer_contacts"),
    _canonicalize("users"),
    _ASSERT_NO_COLLISION,
    "CREATE UNIQUE INDEX ux_users_tenant_whatsapp ON users(tenant_id, whatsapp_e164) "
    "WHERE whatsapp_e164 IS NOT NULL",
    # `encode(gen_random_bytes(12), 'hex')` produz exatamente os 24 hexadecimais
    # que o validador do Gateway exige. `pgcrypto` já é dependência da `0001`,
    # que usa `gen_random_uuid()`.
    "ALTER TABLE users ADD COLUMN public_ref text",
    "UPDATE users SET public_ref = encode(gen_random_bytes(12), 'hex')",
    "ALTER TABLE users ALTER COLUMN public_ref SET NOT NULL",
    "ALTER TABLE users ADD CONSTRAINT ux_users_public_ref UNIQUE (public_ref)",
    "ALTER TABLE users ADD CONSTRAINT ck_users_public_ref "
    "CHECK (public_ref ~ '^[a-f0-9]{24}$')",
    "ALTER TABLE customer_contacts ADD COLUMN public_ref text",
    "UPDATE customer_contacts SET public_ref = encode(gen_random_bytes(12), 'hex')",
    "ALTER TABLE customer_contacts ALTER COLUMN public_ref SET NOT NULL",
    "ALTER TABLE customer_contacts ADD CONSTRAINT ux_customer_contacts_public_ref "
    "UNIQUE (public_ref)",
    "ALTER TABLE customer_contacts ADD CONSTRAINT ck_customer_contacts_public_ref "
    "CHECK (public_ref ~ '^[a-f0-9]{24}$')",
)

# A canonização não é revertida: desfazer o nono dígito devolveria o número a
# uma forma que a Meta não usa mais, e a coluna aceita as duas grafias.
_DOWNGRADE = (
    "ALTER TABLE customer_contacts DROP CONSTRAINT ck_customer_contacts_public_ref",
    "ALTER TABLE customer_contacts DROP CONSTRAINT ux_customer_contacts_public_ref",
    "ALTER TABLE customer_contacts DROP COLUMN public_ref",
    "ALTER TABLE users DROP CONSTRAINT ck_users_public_ref",
    "ALTER TABLE users DROP CONSTRAINT ux_users_public_ref",
    "ALTER TABLE users DROP COLUMN public_ref",
    "DROP INDEX ux_users_tenant_whatsapp",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
