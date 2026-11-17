"""Create individual representative onboarding invitations.

Revision ID: 0029_representative_invites
Revises: 0028_enable_customer_intake
"""

from alembic import op

revision = "0029_representative_invites"
down_revision = "0028_enable_customer_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE representative_invite_status AS ENUM "
        "('PENDING', 'ACCEPTED', 'REVOKED', 'EXPIRED')"
    )
    op.execute("""
        CREATE TABLE representative_invites (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            token_hash varchar(64) NOT NULL,
            status representative_invite_status NOT NULL DEFAULT 'PENDING',
            created_by_user_id uuid NOT NULL REFERENCES users(id),
            representative_user_id uuid REFERENCES users(id),
            expires_at timestamptz NOT NULL,
            accepted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ux_representative_invites_token UNIQUE (token_hash)
        )
    """)
    op.execute(
        "CREATE INDEX ix_representative_invites_tenant_id "
        "ON representative_invites(tenant_id)"
    )
    op.execute(
        "CREATE INDEX ix_representative_invites_tenant_status "
        "ON representative_invites(tenant_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE representative_invites")
    op.execute("DROP TYPE representative_invite_status")
