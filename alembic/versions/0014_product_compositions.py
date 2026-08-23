"""Composição do artigo por fibra: a primeira fatia da camada têxtil.

A matéria-prima do fio vive hoje dentro de `commercial_name` e `specification`
como texto livre. A consequência é medível: "tem poliéster?" — pergunta que o
robô recebe toda semana — não alcança POY, alta tenacidade, Reflex nem
recoberto, que **são** poliéster e não estão marcados como tal em lugar nenhum.

E a composição real é multivalorada e percentual — `PV 30/1 65PES/35CV`,
`REC150/48 92PES 8PUE`, `8/1 APC 70PES/30CO`. Nenhum campo de texto responde
"tem algo com pelo menos 60% de poliéster".

## Por que camada, e não coluna em `products`

`products` carrega preço publicado atrás de si: `price_entries` referencia o
artigo, e o SKU trava no primeiro preço publicado justamente porque é por ele
que a planilha mensal reencontra o artigo (ADR-021). Acrescentar atributo ali
faria cadastro descritivo mexer numa tabela cujo compromisso é comercial.

Camada aditiva também deixa o cadastro incompleto **não bloquear venda**: um
artigo sem composição continua aparecendo na busca e na tabela exatamente como
aparece hoje. Ver ADR-027.

## Três decisões que ficam registradas aqui

**Nada de EAV.** O vocabulário têxtil é fechado — fibra é fibra, e a lista cabe
num seed. Par atributo/valor genérico daria flexibilidade que ninguém pediu em
troca de consulta ilegível e de nenhuma validação possível.

**A soma de 100% não é restrição de banco.** Ela cruza linhas de uma mesma
composição, e um gatilho para isso não se paga num catálogo de centenas de
itens. Fica no serviço, que é o único caminho de escrita.

**`ON DELETE CASCADE` no artigo**, diferente do que a `0013` fez em
`product_group_members`. Lá o vínculo é classificação que alguém montou artigo a
artigo, e apagá-la junto perderia trabalho. Aqui a linha é uma propriedade do
artigo: sem o artigo, `65% PES` não descreve coisa nenhuma. Deixar órfã seria
guardar lixo com aparência de dado.

Nenhuma linha de `products`, `price_entries` ou `product_groups` é tocada.

Revision ID: 0014_product_compositions
Revises: 0013_product_groups
Create Date: 2026-08-23
"""

from alembic import op

revision = "0014_product_compositions"
down_revision = "0013_product_groups"
branch_labels = None
depends_on = None

_UPGRADE = (
    """
    CREATE TABLE fibers (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      code text NOT NULL,
      name text NOT NULL,
      active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE fibers ADD CONSTRAINT ux_fiber_code UNIQUE (tenant_id, code)",
    "CREATE INDEX ix_fibers_tenant ON fibers(tenant_id, active)",
    """
    CREATE TABLE product_compositions (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      fiber_id uuid NOT NULL REFERENCES fibers(id),
      percent numeric(5,2) NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "ALTER TABLE product_compositions ADD CONSTRAINT ux_product_composition "
    "UNIQUE (product_id, fiber_id)",
    # Percentual por linha; a soma é do serviço. Zero e negativo são recusados
    # aqui porque não dependem das outras linhas para serem absurdos.
    "ALTER TABLE product_compositions ADD CONSTRAINT ck_product_composition_percent "
    "CHECK (percent > 0 AND percent <= 100)",
    "CREATE INDEX ix_product_compositions_product ON product_compositions(product_id)",
    # Caminho quente: "artigos de poliéster deste tenant".
    "CREATE INDEX ix_product_compositions_fiber ON product_compositions(tenant_id, fiber_id)",
)

# Reversão segura, ao contrário da `0012`: as duas tabelas são novas, nada fora
# delas passou a depender de composição, e o artigo continua inteiro sem ela.
_DOWNGRADE = (
    "DROP TABLE product_compositions",
    "DROP TABLE fibers",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
