"""Habilita pré-cadastro para representantes com assistente ativo.

Revision ID: 0028_enable_customer_intake
Revises: 0027_customer_intake_review
"""

from alembic import op

revision = "0028_enable_customer_intake"
down_revision = "0027_customer_intake_review"
branch_labels = None
depends_on = None

_CAPABILITY = "CRM_REP_CREATE_CUSTOMER_INTAKE"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO assistant_representative_capabilities
            (tenant_id, user_id, capability_id)
        SELECT settings.tenant_id, settings.user_id, '{_CAPABILITY}'
          FROM assistant_representative_settings AS settings
         WHERE settings.enabled IS TRUE
           AND NOT EXISTS (
               SELECT 1
                 FROM assistant_representative_capabilities AS capability
                WHERE capability.tenant_id = settings.tenant_id
                  AND capability.user_id = settings.user_id
                  AND capability.capability_id = '{_CAPABILITY}'
           )
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM assistant_representative_capabilities "
        f"WHERE capability_id = '{_CAPABILITY}'"
    )
