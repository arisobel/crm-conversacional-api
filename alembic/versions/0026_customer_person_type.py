"""Distingue clientes pessoa fisica e juridica.

Revision ID: 0026_customer_person_type
Revises: 0025_price_proposal_payload
"""

import sqlalchemy as sa

from alembic import op

revision = "0026_customer_person_type"
down_revision = "0025_price_proposal_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("customer_type", sa.String(length=16), nullable=False, server_default="COMPANY"),
    )
    op.create_check_constraint(
        "ck_customers_customer_type",
        "customers",
        "customer_type IN ('INDIVIDUAL', 'COMPANY')",
    )
    op.add_column(
        "customer_intakes",
        sa.Column("customer_type", sa.String(length=16), nullable=False, server_default="COMPANY"),
    )
    op.add_column("customer_intakes", sa.Column("trade_name", sa.Text(), nullable=True))
    op.add_column("customer_intakes", sa.Column("document_number", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("customer_intakes", "document_number")
    op.drop_column("customer_intakes", "trade_name")
    op.drop_column("customer_intakes", "customer_type")
    op.drop_constraint("ck_customers_customer_type", "customers", type_="check")
    op.drop_column("customers", "customer_type")
