"""Add retry-safe one-hour reminder notification claims.

Revision ID: 0021_reminder_claims
Revises: 0020_representative_reminders
"""

from alembic import op

revision = "0021_reminder_claims"
down_revision = "0020_representative_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE representative_reminders "
        "ADD COLUMN IF NOT EXISTS notification_claimed_at timestamptz"
    )
    op.execute(
        "ALTER TABLE representative_reminders "
        "ADD COLUMN IF NOT EXISTS notification_claim_token uuid"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reminders_notification_claim "
        "ON representative_reminders(notified_at, notification_claimed_at, due_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_reminders_notification_claim")
    op.execute("ALTER TABLE representative_reminders DROP COLUMN notification_claim_token")
    op.execute("ALTER TABLE representative_reminders DROP COLUMN notification_claimed_at")
