"""Add saved conversational regression scenarios.

Revision ID: 0032_simulation_scenarios
Revises: 0031_customer_fact_evidence
"""

from alembic import op

revision = "0032_simulation_scenarios"
down_revision = "0031_customer_fact_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE conversation_simulation_scenarios (
          id uuid PRIMARY KEY,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          name varchar(120) NOT NULL,
          mode varchar(32) NOT NULL,
          representative_user_id uuid REFERENCES users(id),
          message text NOT NULL,
          expected_status varchar(32) NOT NULL,
          expected_capability_id varchar(120),
          expected_action varchar(120),
          expected_fact_text varchar(240),
          last_passed boolean,
          last_result text,
          last_run_at timestamptz,
          created_by_user_id uuid NOT NULL REFERENCES users(id),
          active boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_simulation_scenario_mode CHECK (
            mode IN ('REPRESENTATIVE_ASSISTANT', 'CUSTOMER_SERVICE')
          )
        )
    """)
    op.execute(
        "CREATE INDEX ix_conversation_simulation_scenarios_tenant_id "
        "ON conversation_simulation_scenarios(tenant_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE conversation_simulation_scenarios")
