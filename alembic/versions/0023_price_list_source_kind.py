"""Registra o canal exato de entrada de cada lote de preços.

Revision ID: 0023_price_list_source_kind
Revises: 0022_price_update_proposals
"""

import sqlalchemy as sa

from alembic import op

revision = "0023_price_list_source_kind"
down_revision = "0022_price_update_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("price_lists", sa.Column("source_kind", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("price_lists", "source_kind")
