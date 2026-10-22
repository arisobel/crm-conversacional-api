"""Store assistant settings without activating them.

Revision ID: 0018_assistant_settings
Revises: 0017_whatsapp_states
"""

from alembic import op

revision = "0018_assistant_settings"
down_revision = "0017_whatsapp_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD CONSTRAINT ux_users_tenant_id UNIQUE (tenant_id, id)")
    op.execute("""
        CREATE TABLE assistant_organization_settings (
            tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
            enabled boolean NOT NULL DEFAULT false,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE assistant_representative_settings (
            tenant_id uuid NOT NULL,
            user_id uuid NOT NULL,
            enabled boolean NOT NULL DEFAULT false,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, user_id),
            CONSTRAINT fk_assistant_rep_user_tenant FOREIGN KEY (tenant_id, user_id)
                REFERENCES users (tenant_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE assistant_representative_capabilities (
            tenant_id uuid NOT NULL,
            user_id uuid NOT NULL,
            capability_id varchar(80) NOT NULL,
            PRIMARY KEY (tenant_id, user_id, capability_id),
            CONSTRAINT fk_assistant_capability_rep FOREIGN KEY (tenant_id, user_id)
                REFERENCES assistant_representative_settings (tenant_id, user_id)
                ON DELETE CASCADE
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE assistant_representative_capabilities")
    op.execute("DROP TABLE assistant_representative_settings")
    op.execute("DROP TABLE assistant_organization_settings")
    op.execute("ALTER TABLE users DROP CONSTRAINT ux_users_tenant_id")
