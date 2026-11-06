"""Identify WhatsApp price update proposals and their representative.

Revision ID: 0022_price_update_proposals
Revises: 0021_reminder_notification_claims
"""

from alembic import op

revision = "0022_price_update_proposals"
down_revision = "0021_reminder_notification_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE price_lists ADD COLUMN created_by uuid REFERENCES users(id)")
    op.execute("ALTER TABLE price_lists ADD COLUMN source_wamid varchar(255)")
    op.execute(
        "CREATE UNIQUE INDEX ux_price_lists_whatsapp_source "
        "ON price_lists(tenant_id, source_wamid) WHERE source_wamid IS NOT NULL"
    )
    # O representante jÃ¡ habilitado no assistente recebe as duas capacidades
    # autorizadas para o MVP. Perfis desabilitados continuam sem acesso.
    op.execute("""
        INSERT INTO assistant_representative_capabilities
            (tenant_id, user_id, capability_id)
        SELECT settings.tenant_id, settings.user_id, capability.capability_id
        FROM assistant_representative_settings AS settings
        CROSS JOIN (
            VALUES ('CRM_REP_CREATE_REMINDER'), ('CRM_REP_UPDATE_PRICES')
        ) AS capability(capability_id)
        WHERE settings.enabled = true
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM assistant_representative_capabilities
        WHERE capability_id IN ('CRM_REP_CREATE_REMINDER', 'CRM_REP_UPDATE_PRICES')
    """)
    op.execute("DROP INDEX ux_price_lists_whatsapp_source")
    op.execute("ALTER TABLE price_lists DROP COLUMN source_wamid")
    op.execute("ALTER TABLE price_lists DROP COLUMN created_by")
