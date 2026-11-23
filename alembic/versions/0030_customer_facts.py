"""Add confirmed customer facts used by conversational memory.

Revision ID: 0030_customer_facts
Revises: 0029_representative_invites
"""

from alembic import op

revision = "0030_customer_facts"
down_revision = "0029_representative_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE customer_facts (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            customer_id uuid NOT NULL REFERENCES customers(id),
            category varchar(32) NOT NULL DEFAULT 'OTHER',
            fact_text text NOT NULL,
            source varchar(16) NOT NULL DEFAULT 'PORTAL',
            status varchar(16) NOT NULL DEFAULT 'CONFIRMED',
            created_by_user_id uuid REFERENCES users(id),
            confirmed_by_user_id uuid REFERENCES users(id),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_customer_facts_category CHECK (
                category IN ('PREFERENCE', 'PERSONAL_CONTEXT', 'COMMERCIAL', 'OTHER')
            ),
            CONSTRAINT ck_customer_facts_source CHECK (
                source IN ('PORTAL', 'WHATSAPP', 'ASSISTANT')
            ),
            CONSTRAINT ck_customer_facts_status CHECK (
                status IN ('SUGGESTED', 'CONFIRMED', 'REJECTED')
            )
        )
    """)
    op.execute("CREATE INDEX ix_customer_facts_tenant_id ON customer_facts(tenant_id)")
    op.execute("CREATE INDEX ix_customer_facts_customer_id ON customer_facts(customer_id)")
    op.execute(
        "CREATE INDEX ix_customer_facts_customer_status "
        "ON customer_facts(customer_id, active, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE customer_facts")
