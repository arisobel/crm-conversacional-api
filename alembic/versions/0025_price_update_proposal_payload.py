"""Guarda a previa completa de alteracoes e novos produtos.

Revision ID: 0025_price_proposal_payload
Revises: 0024_price_list_source_files
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0025_price_proposal_payload"
down_revision = "0024_price_list_source_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    proposal_json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column("price_lists", sa.Column("proposal_payload", proposal_json, nullable=True))


def downgrade() -> None:
    op.drop_column("price_lists", "proposal_payload")
