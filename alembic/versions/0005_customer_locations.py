"""Give each customer the places where it receives, with one default per customer.

R2 da direção de CRM de representantes. O ICMS depende da UF de destino e um
cliente pode receber em mais de uma; `customers.state_code` permanece como UF
fiscal do cadastro.

O backfill cria uma localidade `Principal` por cliente com a UF que ele já tem,
inclusive para clientes inativos: a coluna de origem não é apagada, então o
downgrade não perde informação.

Revision ID: 0005_customer_locations
Revises: 0004_representative_portfolio
Create Date: 2026-08-05
"""

from alembic import op

revision = "0005_customer_locations"
down_revision = "0004_representative_portfolio"
branch_labels = None
depends_on = None

_UPGRADE = (
    """
    CREATE TABLE customer_locations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      customer_id uuid NOT NULL REFERENCES customers(id),
      label text NOT NULL,
      state_code char(2) NOT NULL CHECK (state_code ~ '^[A-Z]{2}$'),
      city text,
      is_default boolean NOT NULL DEFAULT false,
      active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX ux_default_location_per_customer "
    "ON customer_locations(customer_id) WHERE is_default AND active",
    "CREATE INDEX ix_customer_locations_customer ON customer_locations(customer_id, active)",
    """
    INSERT INTO customer_locations
      (tenant_id, customer_id, label, state_code, is_default, active)
    SELECT tenant_id, id, 'Principal', state_code, true, true
    FROM customers
    """,
)

_DOWNGRADE = ("DROP TABLE customer_locations",)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
