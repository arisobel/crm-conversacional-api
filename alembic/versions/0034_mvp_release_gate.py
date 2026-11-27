"""Add evidence and frozen scope for the MVP release gate.

Revision ID: 0034_mvp_release_gate
Revises: 0033_simulation_quality
"""

from alembic import op

revision = "0034_mvp_release_gate"
down_revision = "0033_simulation_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE mvp_release_controls (
          tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
          scope_version varchar(40) NOT NULL DEFAULT 'MVP-1',
          scope_frozen_at timestamptz,
          scope_frozen_by_user_id uuid REFERENCES users(id),
          scope_snapshot_hash varchar(64),
          scope_snapshot jsonb,
          acceptance_checks jsonb NOT NULL DEFAULT '{}'::jsonb,
          updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.drop_table("mvp_release_controls")
