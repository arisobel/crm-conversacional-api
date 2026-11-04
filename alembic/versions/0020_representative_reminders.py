"""Create the commercial reminder agenda.

Revision ID: 0020_representative_reminders
Revises: 0019_conversation_behavior
"""

from alembic import op

revision = "0020_representative_reminders"
down_revision = "0019_conversation_behavior"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE representative_reminders (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            representative_user_id uuid NOT NULL REFERENCES users(id),
            customer_id uuid REFERENCES customers(id),
            customer_contact_id uuid REFERENCES customer_contacts(id),
            origin varchar(24) NOT NULL,
            kind varchar(24) NOT NULL,
            status varchar(32) NOT NULL,
            note text NOT NULL,
            due_at timestamptz NOT NULL,
            timezone varchar(64) NOT NULL DEFAULT 'America/Sao_Paulo',
            source_wamid varchar(255) NOT NULL,
            source_line_reference text,
            notified_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ux_reminder_source_wamid UNIQUE (tenant_id, source_wamid),
            CONSTRAINT ck_reminder_status CHECK (status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'COMPLETED', 'CANCELLED')),
            CONSTRAINT ck_reminder_origin CHECK (origin IN ('CUSTOMER', 'REPRESENTATIVE')),
            CONSTRAINT ck_reminder_kind CHECK (kind IN ('CALL', 'MEETING', 'FOLLOW_UP'))
        )
    """)
    op.execute("CREATE INDEX ix_reminders_due ON representative_reminders(status, due_at)")
    op.execute("CREATE INDEX ix_reminders_representative ON representative_reminders(representative_user_id, due_at)")
    op.execute("CREATE INDEX ix_representative_reminders_tenant_id ON representative_reminders(tenant_id)")
    op.execute("CREATE INDEX ix_representative_reminders_customer_id ON representative_reminders(customer_id)")


def downgrade() -> None:
    op.execute("DROP TABLE representative_reminders")

