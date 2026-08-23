"""Grupo de artigo: agrupamento livre e multivalorado, ao lado da família.

O eixo de material do disparo (D1) ia derivar de `product_families`. Não serve,
e o retorno do Charles mostrou por quê: ele citou "poliéster", "viscose" e
"alta-tenacidade" como grupos irmãos, mas alta tenacidade é propriedade do fio
de poliéster, não um material ao lado dele. Um mesmo artigo é os dois.

Família não pode virar N↔N para acomodar isso. Ela é **layout**: agrupa e
ordena a tabela de preço que o cliente recebe pelo WhatsApp, e um artigo em
duas famílias não teria sob qual cabeçalho imprimir. É a mesma separação de
responsabilidades do ADR-021 — cada fonte dona de uma coisa.

Entram então duas tabelas, e `products.family_id` fica exatamente como está.

`normalized_name` com unicidade é a guarda que sobrevive à tela. A criação de
grupo é livre e a taxonomia é compartilhada; sem essa restrição, "poliester",
"poliéster" e "POLIÉSTER" nascem como três grupos e o público de um disparo
racha em silêncio. O combobox evita a maior parte, mas ele não protege uma
chamada de API nem um clique apressado.

Nenhuma linha existente é tocada.

Revision ID: 0013_product_groups
Revises: 0012_representative_notes
Create Date: 2026-08-23
"""

from alembic import op

revision = "0013_product_groups"
down_revision = "0012_representative_notes"
branch_labels = None
depends_on = None

_UPGRADE = (
    """
    CREATE TABLE product_groups (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      name text NOT NULL,
      normalized_name text NOT NULL,
      active boolean NOT NULL DEFAULT true,
      created_by uuid REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX ix_product_groups_tenant ON product_groups(tenant_id, active)",
    "ALTER TABLE product_groups ADD CONSTRAINT ux_product_group_name "
    "UNIQUE (tenant_id, normalized_name)",
    """
    CREATE TABLE product_group_members (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      group_id uuid NOT NULL REFERENCES product_groups(id) ON DELETE CASCADE,
      product_id uuid NOT NULL REFERENCES products(id),
      added_by uuid REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE product_group_members ADD CONSTRAINT ux_product_group_member "
    "UNIQUE (group_id, product_id)",
    # O caminho quente é "quais grupos este artigo tem", na ficha do artigo, e
    # "quais artigos deste grupo", ao montar o público do disparo.
    "CREATE INDEX ix_product_group_members_product ON product_group_members(product_id)",
    "CREATE INDEX ix_product_group_members_group ON product_group_members(group_id)",
)

# Reversão é segura: as duas tabelas são novas e nada fora delas passou a
# depender do grupo. Diferente da `0012`, aqui não há dado que só exista neste
# lugar — a etiqueta é classificação, e o artigo continua inteiro sem ela.
_DOWNGRADE = (
    "DROP TABLE product_group_members",
    "DROP TABLE product_groups",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
