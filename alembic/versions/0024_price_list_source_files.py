"""Armazena o arquivo original usado em cada lote de precos.

Revision ID: 0024_price_list_source_files
Revises: 0023_price_list_source_kind
"""

import sqlalchemy as sa

from alembic import op

revision = "0024_price_list_source_files"
down_revision = "0023_price_list_source_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_list_source_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("price_list_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=160), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["price_list_id"], ["price_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("price_list_id"),
    )
    op.create_index(
        "ix_price_list_source_files_tenant_id", "price_list_source_files", ["tenant_id"]
    )
    op.create_index(
        "ix_price_list_source_files_price_list_id", "price_list_source_files", ["price_list_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_price_list_source_files_price_list_id", table_name="price_list_source_files")
    op.drop_index("ix_price_list_source_files_tenant_id", table_name="price_list_source_files")
    op.drop_table("price_list_source_files")
