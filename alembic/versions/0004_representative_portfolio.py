"""Attach customers to a representative and keep the assignment trail.

R1 da direção de CRM de representantes. Ver ADR-013 e
docs/40_delivery/F5_REPRESENTATIVE_PORTAL.md.

Nenhum cliente existente recebe titular: a coluna nasce nula e a designação é
uma decisão comercial explícita, feita pelo portal e registrada no histórico.

Revision ID: 0004_representative_portfolio
Revises: 0003_identity
Create Date: 2026-08-05
"""

from alembic import op

revision = "0004_representative_portfolio"
down_revision = "0003_identity"
branch_labels = None
depends_on = None

_UPGRADE = (
    "ALTER TABLE customers ADD COLUMN owner_user_id uuid REFERENCES users(id)",
    "CREATE INDEX ix_customers_owner ON customers(tenant_id, owner_user_id) WHERE active",
    """
    CREATE TABLE customer_assignment_history (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      customer_id uuid NOT NULL REFERENCES customers(id),
      user_id uuid REFERENCES users(id),
      assigned_at timestamptz NOT NULL DEFAULT now(),
      assigned_by uuid NOT NULL REFERENCES users(id),
      reason text
    )
    """,
    "CREATE INDEX ix_customer_assignment_history_customer "
    "ON customer_assignment_history(customer_id, assigned_at DESC)",
)

_DOWNGRADE = (
    "DROP TABLE customer_assignment_history",
    "DROP INDEX ix_customers_owner",
    "ALTER TABLE customers DROP COLUMN owner_user_id",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
