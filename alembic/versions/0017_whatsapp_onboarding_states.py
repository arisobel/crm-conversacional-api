"""Allow cancelled and expired WhatsApp onboarding attempts.

Revision ID: 0017_whatsapp_states
Revises: 0016_whatsapp_onboarding
"""

from alembic import op

revision = "0017_whatsapp_states"
down_revision = "0016_whatsapp_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE whatsapp_connection_status ADD VALUE IF NOT EXISTS 'CANCELLED'")
    op.execute("ALTER TYPE whatsapp_connection_status ADD VALUE IF NOT EXISTS 'EXPIRED'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values. The application downgrade
    # must not be run while rows use either terminal status.
    pass
