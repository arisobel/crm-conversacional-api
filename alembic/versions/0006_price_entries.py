"""Make competence + product the idempotency key of the current price.

R3 da direção de CRM de representantes. Ver ADR-014.

`price_entries` passa a ser a fonte de verdade do preço vigente, com
`UNIQUE(tenant_id, reference_month, product_id)`. `price_lists` e
`price_list_items` continuam existindo como o lote de importação revisável que o
ADR-009 exige; a ativação do lote promove os valores para `price_entries`.

O backfill traz a tabela `ACTIVE` de cada competência. Se encontrar dois preços
para o mesmo produto no mesmo mês, ele **para** — resolver por "último vence"
escolheria em silêncio qual preço vale para um cliente real.

Revision ID: 0006_price_entries
Revises: 0005_customer_locations
Create Date: 2026-08-05
"""

from alembic import op

revision = "0006_price_entries"
down_revision = "0005_customer_locations"
branch_labels = None
depends_on = None

_UPGRADE = (
    "ALTER TYPE price_list_status ADD VALUE IF NOT EXISTS 'PUBLISHED'",
    """
    CREATE TABLE price_entries (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      reference_month date NOT NULL
        CHECK (reference_month = date_trunc('month', reference_month)::date),
      product_id uuid NOT NULL REFERENCES products(id),
      base_price numeric(14,4) NOT NULL CHECK (base_price >= 0),
      base_tax_rate numeric(6,3) CHECK (base_tax_rate IS NULL OR base_tax_rate BETWEEN 0 AND 100),
      availability availability_status NOT NULL DEFAULT 'CONSULT',
      expected_arrival_date date,
      available_quantity_kg numeric(14,3)
        CHECK (available_quantity_kg IS NULL OR available_quantity_kg >= 0),
      arrival_note text,
      notes text,
      display_order integer NOT NULL DEFAULT 0,
      source_batch_id uuid REFERENCES price_lists(id),
      published_at timestamptz NOT NULL DEFAULT now(),
      published_by uuid REFERENCES users(id),
      CONSTRAINT ux_price_entry_month_product UNIQUE (tenant_id, reference_month, product_id)
    )
    """,
    "CREATE INDEX ix_price_entries_month ON price_entries(tenant_id, reference_month)",
    """
    CREATE TABLE price_entry_revisions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      reference_month date NOT NULL,
      product_id uuid NOT NULL REFERENCES products(id),
      previous jsonb,
      current jsonb NOT NULL,
      batch_id uuid REFERENCES price_lists(id),
      changed_by uuid REFERENCES users(id),
      changed_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX ix_price_entry_revisions_product "
    "ON price_entry_revisions(tenant_id, reference_month, product_id, changed_at DESC)",
    # Conflito antes de gravar: duas tabelas ACTIVE com o mesmo produto e mês.
    """
    DO $$
    DECLARE conflitos integer;
    BEGIN
      SELECT count(*) INTO conflitos FROM (
        SELECT pl.tenant_id, pl.reference_month, pli.product_id
        FROM price_list_items pli
        JOIN price_lists pl ON pl.id = pli.price_list_id
        WHERE pl.status = 'ACTIVE'
        GROUP BY pl.tenant_id, pl.reference_month, pli.product_id
        HAVING count(*) > 1
      ) AS duplicados;
      IF conflitos > 0 THEN
        RAISE EXCEPTION
          'Backfill interrompido: % combinacao(oes) de (tenant, competencia, produto) '
          'com mais de um preco ATIVO. Resolva antes de migrar.', conflitos;
      END IF;
    END $$;
    """,
    """
    INSERT INTO price_entries (
      tenant_id, reference_month, product_id, base_price, base_tax_rate,
      availability, expected_arrival_date, available_quantity_kg, arrival_note,
      notes, display_order, source_batch_id
    )
    SELECT
      pl.tenant_id, pl.reference_month, pli.product_id, pli.base_price,
      COALESCE(pli.item_tax_rate, pl.base_tax_rate),
      pli.availability, pli.expected_arrival_date, pli.available_quantity_kg,
      pli.arrival_note, pli.notes, pli.display_order, pl.id
    FROM price_list_items pli
    JOIN price_lists pl ON pl.id = pli.price_list_id
    WHERE pl.status = 'ACTIVE'
    """,
    """
    INSERT INTO price_entry_revisions
      (tenant_id, reference_month, product_id, previous, current, batch_id)
    SELECT
      tenant_id, reference_month, product_id, NULL,
      jsonb_build_object(
        'base_price', base_price,
        'availability', availability,
        'source', 'backfill_0006'
      ),
      source_batch_id
    FROM price_entries
    """,
)

_DOWNGRADE = (
    "DROP TABLE price_entry_revisions",
    "DROP TABLE price_entries",
    # `PUBLISHED` permanece no enum: o PostgreSQL não remove valor de tipo
    # enumerado, e recriar o tipo exigiria reescrever price_lists.
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
