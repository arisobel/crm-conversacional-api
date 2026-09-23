"""CRM commercial projection for Gateway WhatsApp onboarding.

Revision ID: 0016_whatsapp_onboarding
Revises: 0015_whatsapp_campaigns
Create Date: 2026-09-23
"""

from alembic import op

revision = "0016_whatsapp_onboarding"
down_revision = "0015_whatsapp_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE whatsapp_connection_status AS ENUM ('NOT_CONNECTED', 'CONNECTING', 'CONNECTED', 'ACTION_REQUIRED', 'CONFLICT', 'FAILED')")
    op.execute("""
      CREATE TABLE representative_whatsapp_connections (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id),
        representative_user_id uuid NOT NULL REFERENCES users(id),
        provider varchar(32) NOT NULL DEFAULT 'whatsapp',
        status whatsapp_connection_status NOT NULL DEFAULT 'CONNECTING',
        idempotency_key varchar(64) NOT NULL UNIQUE,
        gateway_onboarding_id text, gateway_line_reference text,
        display_phone_number text, last_gateway_status text, failure_code text,
        started_at timestamptz NOT NULL DEFAULT now(), connected_at timestamptz,
        failed_at timestamptz, created_by_user_id uuid NOT NULL REFERENCES users(id),
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
      )
    """)
    op.execute("CREATE UNIQUE INDEX ux_rwc_one_active_per_representative ON representative_whatsapp_connections(tenant_id, representative_user_id) WHERE status IN ('CONNECTING', 'CONNECTED', 'ACTION_REQUIRED')")
    op.execute("CREATE UNIQUE INDEX ux_rwc_gateway_onboarding ON representative_whatsapp_connections(tenant_id, gateway_onboarding_id)")


def downgrade() -> None:
    op.execute("DROP TABLE representative_whatsapp_connections")
    op.execute("DROP TYPE whatsapp_connection_status")
