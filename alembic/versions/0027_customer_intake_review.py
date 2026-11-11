"""Permite ficha parcial e conferÃªncia campo a campo no prÃ©-cadastro.

Revision ID: 0027_customer_intake_review
Revises: 0026_customer_person_type
"""

import sqlalchemy as sa

from alembic import op

revision = "0027_customer_intake_review"
down_revision = "0026_customer_person_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("customer_intakes", "state_code", existing_type=sa.CHAR(2), nullable=True)
    op.add_column("customer_intakes", sa.Column("contact_name", sa.Text(), nullable=True))
    op.add_column(
        "customer_intakes",
        sa.Column("confirmed_fields", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.execute("UPDATE customer_intakes SET state_code = 'SP' WHERE state_code IS NULL")
    op.drop_column("customer_intakes", "confirmed_fields")
    op.drop_column("customer_intakes", "contact_name")
    op.alter_column("customer_intakes", "state_code", existing_type=sa.CHAR(2), nullable=False)
