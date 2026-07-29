"""Create the schema defined by the approved initial PostgreSQL DDL.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-28
"""

from pathlib import Path

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

_ROOT = Path(__file__).resolve().parents[2]
_DDL_PATH = _ROOT / "db" / "migrations" / "0001_initial.sql"


def _statements() -> list[str]:
    ddl = _DDL_PATH.read_text(encoding="utf-8")
    return [
        statement.strip()
        for statement in ddl.split(";")
        if statement.strip() and statement.strip() not in {"BEGIN", "COMMIT"}
    ]


def upgrade() -> None:
    for statement in _statements():
        op.execute(statement)


def downgrade() -> None:
    for table in (
        "outbound_messages",
        "offer_items",
        "offers",
        "messages",
        "inbound_events",
        "conversations",
        "tax_rules",
        "freight_rules",
        "commercial_terms",
        "price_list_items",
        "price_lists",
        "customer_preferred_products",
        "products",
        "product_families",
        "customer_contacts",
        "customers",
        "tenants",
    ):
        op.execute(f"DROP TABLE {table}")
    for type_name in (
        "delivery_status",
        "message_direction",
        "offer_status",
        "commercial_term_type",
        "adjustment_type",
        "price_list_status",
        "availability_status",
    ):
        op.execute(f"DROP TYPE {type_name}")
