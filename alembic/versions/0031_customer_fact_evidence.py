"""Add evidence and confidence to conversational customer facts.

Revision ID: 0031_customer_fact_evidence
Revises: 0030_customer_facts
"""

from alembic import op

revision = "0031_customer_fact_evidence"
down_revision = "0030_customer_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE customer_facts
          ADD COLUMN source_interaction_id uuid REFERENCES customer_interactions(id),
          ADD COLUMN source_excerpt text,
          ADD COLUMN confidence_score integer,
          ADD CONSTRAINT ck_customer_facts_confidence CHECK (
            confidence_score IS NULL OR confidence_score BETWEEN 0 AND 100
          )
    """)
    op.execute(
        "CREATE INDEX ix_customer_facts_source_interaction ON customer_facts(source_interaction_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_customer_facts_source_interaction")
    op.execute("""
        ALTER TABLE customer_facts
          DROP CONSTRAINT ck_customer_facts_confidence,
          DROP COLUMN confidence_score,
          DROP COLUMN source_excerpt,
          DROP COLUMN source_interaction_id
    """)
