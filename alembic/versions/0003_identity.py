"""Create portal identity: users, server-side sessions and the audit trail.

R0 da direção de CRM de representantes. Ver ADR-013 e
docs/40_delivery/F5_REPRESENTATIVE_PORTAL.md.

Revision ID: 0003_identity
Revises: 0002_price_item_order
Create Date: 2026-08-05
"""

from alembic import op

revision = "0003_identity"
down_revision = "0002_price_item_order"
branch_labels = None
depends_on = None

_UPGRADE = (
    "CREATE TYPE user_role AS ENUM ('ADMIN','MANAGER','REPRESENTATIVE')",
    """
    CREATE TABLE users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      full_name text NOT NULL,
      email text NOT NULL
        CHECK (email = lower(email))
        CHECK (email ~ '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'),
      password_hash text NOT NULL,
      role user_role NOT NULL,
      whatsapp_e164 text CHECK (whatsapp_e164 ~ '^\\+[1-9][0-9]{7,14}$'),
      active boolean NOT NULL DEFAULT true,
      failed_login_attempts integer NOT NULL DEFAULT 0 CHECK (failed_login_attempts >= 0),
      locked_until timestamptz,
      last_login_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT ux_users_tenant_email UNIQUE (tenant_id, email)
    )
    """,
    "CREATE INDEX ix_users_tenant_role ON users(tenant_id, role) WHERE active",
    """
    CREATE TABLE user_sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      user_id uuid NOT NULL REFERENCES users(id),
      token_hash text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      last_seen_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NOT NULL,
      absolute_expires_at timestamptz NOT NULL,
      revoked_at timestamptz,
      ip_address text,
      user_agent text,
      CONSTRAINT ux_user_sessions_token UNIQUE (token_hash),
      CONSTRAINT ck_user_sessions_window CHECK (absolute_expires_at >= expires_at)
    )
    """,
    "CREATE INDEX ix_user_sessions_user ON user_sessions(user_id, expires_at)",
    """
    CREATE TABLE audit_log (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid REFERENCES tenants(id),
      actor_user_id uuid REFERENCES users(id),
      action text NOT NULL,
      entity text NOT NULL,
      entity_id uuid,
      before jsonb,
      after jsonb,
      occurred_at timestamptz NOT NULL DEFAULT now(),
      request_id text
    )
    """,
    "CREATE INDEX ix_audit_log_occurred ON audit_log(tenant_id, occurred_at)",
    "CREATE INDEX ix_audit_log_actor ON audit_log(actor_user_id, occurred_at)",
)

_DOWNGRADE = (
    "DROP TABLE audit_log",
    "DROP TABLE user_sessions",
    "DROP TABLE users",
    "DROP TYPE user_role",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
