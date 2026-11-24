"""Add multi-turn context and reply quality checks to simulation scenarios.

Revision ID: 0033_simulation_quality
Revises: 0032_simulation_scenarios
"""

from alembic import op

revision = "0033_simulation_quality"
down_revision = "0032_simulation_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversation_simulation_scenarios
          ADD COLUMN conversation_history jsonb NOT NULL DEFAULT '[]'::jsonb,
          ADD COLUMN expected_reply_contains text,
          ADD COLUMN forbidden_reply_contains text,
          ADD COLUMN max_questions integer,
          ADD CONSTRAINT ck_simulation_scenario_max_questions
            CHECK (max_questions IS NULL OR max_questions BETWEEN 0 AND 5)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE conversation_simulation_scenarios
          DROP CONSTRAINT ck_simulation_scenario_max_questions,
          DROP COLUMN max_questions,
          DROP COLUMN forbidden_reply_contains,
          DROP COLUMN expected_reply_contains,
          DROP COLUMN conversation_history
    """)
