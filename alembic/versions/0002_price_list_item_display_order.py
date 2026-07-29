"""Add explicit display order to imported price-list items.

Revision ID: 0002_price_list_item_display_order
Revises: 0001_initial_schema
Create Date: 2026-07-29
"""

from alembic import op

revision = "0002_price_list_item_display_order"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE price_list_items ADD COLUMN display_order integer NOT NULL DEFAULT 0"
    )
    op.execute(
        "CREATE INDEX ix_price_list_items_display_order "
        "ON price_list_items(price_list_id, display_order)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_price_list_items_display_order")
    op.execute("ALTER TABLE price_list_items DROP COLUMN display_order")
