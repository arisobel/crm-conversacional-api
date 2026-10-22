"""Store drafts of conversation behavior for each bot.

Revision ID: 0019_conversation_behavior
Revises: 0018_assistant_settings
"""

from alembic import op

revision = "0019_conversation_behavior"
down_revision = "0018_assistant_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE conversation_behavior_settings (
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            bot_kind varchar(20) NOT NULL,
            tone varchar(40) NOT NULL,
            instructions text NOT NULL,
            context_minutes integer NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, bot_kind),
            CONSTRAINT ck_behavior_bot_kind CHECK (bot_kind IN ('ASSISTANT', 'COEXISTENCE')),
            CONSTRAINT ck_behavior_context_minutes CHECK (context_minutes BETWEEN 15 AND 1440)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE conversation_behavior_settings")
