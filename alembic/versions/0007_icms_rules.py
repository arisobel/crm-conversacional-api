"""Resolve ICMS by origin/destination pair, with explicit precedence.

R4 da direção de CRM de representantes. Ver ADR-015.

`tax_rules`, pendurada em `price_list_id` e sem par de UFs, fica depreciada:
deixa de ser lida, mas não é removida — há dado potencial em produção e a
remoção exige ADR próprio.

Revision ID: 0007_icms_rules
Revises: 0006_price_entries
Create Date: 2026-08-06
"""

from alembic import op

revision = "0007_icms_rules"
down_revision = "0006_price_entries"
branch_labels = None
depends_on = None

_UPGRADE = (
    "ALTER TABLE tenants ADD COLUMN origin_state_code char(2) "
    "CHECK (origin_state_code IS NULL OR origin_state_code ~ '^[A-Z]{2}$')",
    """
    CREATE TABLE icms_rules (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      origin_state char(2) NOT NULL CHECK (origin_state ~ '^[A-Z]{2}$'),
      destination_state char(2) NOT NULL CHECK (destination_state ~ '^[A-Z]{2}$'),
      product_id uuid REFERENCES products(id),
      family_id uuid REFERENCES product_families(id),
      customer_id uuid REFERENCES customers(id),
      tax_rate numeric(6,3) NOT NULL CHECK (tax_rate BETWEEN 0 AND 100),
      valid_from date NOT NULL,
      valid_until date,
      priority integer NOT NULL DEFAULT 100,
      active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK (valid_until IS NULL OR valid_until > valid_from),
      -- Produto e família são níveis diferentes de especificidade; aceitar os
      -- dois na mesma regra tornaria a precedência ambígua.
      CHECK (product_id IS NULL OR family_id IS NULL)
    )
    """,
    "CREATE INDEX ix_icms_rules_lookup "
    "ON icms_rules(tenant_id, origin_state, destination_state, valid_from) WHERE active",
    "COMMENT ON TABLE tax_rules IS "
    "'DEPRECIADA desde 0007: substituida por icms_rules. Nao e lida pela aplicacao.'",
)

_DOWNGRADE = (
    "COMMENT ON TABLE tax_rules IS NULL",
    "DROP TABLE icms_rules",
    "ALTER TABLE tenants DROP COLUMN origin_state_code",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
