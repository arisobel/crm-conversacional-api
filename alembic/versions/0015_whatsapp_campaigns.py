"""Projeção comercial de campanhas de WhatsApp.

F6.1 do [plano F6](../../docs/40_delivery/F6_WHATSAPP_CAMPAIGNS.md), ADR-028.

Duas tabelas novas, nada existente é alterado — como a `0011`, é uma migração
barata: não há dado a canonizar e a reversão é um `DROP` limpo enquanto nenhuma
campanha tiver saído do estado de rascunho.

Nenhuma coluna aqui dispara nada. Os campos `gateway_*` nascem nulos e são o
lugar reservado para a correlação com o Gateway quando o contrato da F6.4
existir; até lá, o CRM só cria, consulta e cancela rascunhos.

As guardas moram no banco, não só no serviço:

`ux_whatsapp_campaigns_idempotency` — reentrega do comando de criação não abre
segunda campanha; duas entregas concorrentes passam pela checagem do serviço
nas duas, e quem decide é a unicidade.

`ck_whatsapp_campaigns_confirmation` — rascunho não tem confirmação nem
correlação externa; confirmada em diante carrega a confirmação que a autorizou.

`ck_wcr_exclusion` / `ck_wcr_contact` — exclusão tem motivo, não excluído não
carrega motivo, e linha sem contato só existe como exclusão: um destinatário
elegível sem telefone prometeria um envio impossível.

`ux_wcr_contact` / `ux_wcr_customer_without_contact` — a unicidade do
destinatário é por contato quando ele existe e por cliente quando não existe.
São dois índices parciais porque `UNIQUE` com coluna nula não deduplica no
PostgreSQL.

Revision ID: 0015_whatsapp_campaigns
Revises: 0014_product_compositions
Create Date: 2026-09-02
"""

from alembic import op

revision = "0015_whatsapp_campaigns"
down_revision = "0014_product_compositions"
branch_labels = None
depends_on = None

_UPGRADE = (
    "CREATE TYPE whatsapp_campaign_status AS ENUM"
    " ('DRAFT', 'AWAITING_CONFIRMATION', 'CONFIRMED', 'IN_PROGRESS',"
    " 'COMPLETED', 'CANCELLED', 'FAILED')",
    "CREATE TYPE whatsapp_campaign_recipient_status AS ENUM"
    " ('PENDING', 'EXCLUDED', 'SENT', 'DELIVERED', 'READ', 'FAILED')",
    """
    CREATE TABLE whatsapp_campaigns (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      created_by_user_id uuid NOT NULL REFERENCES users(id),
      representative_user_id uuid REFERENCES users(id),
      idempotency_key text NOT NULL,
      status whatsapp_campaign_status NOT NULL DEFAULT 'DRAFT',
      criteria_snapshot jsonb NOT NULL,
      audience_summary_snapshot jsonb NOT NULL,
      template_snapshot jsonb NOT NULL,
      variables_snapshot jsonb,
      confirmation jsonb,
      gateway_campaign_id text,
      gateway_status text,
      gateway_updated_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT ck_whatsapp_campaigns_confirmation CHECK (
        (status IN ('DRAFT', 'AWAITING_CONFIRMATION')
         AND confirmation IS NULL AND gateway_campaign_id IS NULL)
        OR (status IN ('CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'FAILED')
            AND confirmation IS NOT NULL)
        OR (status = 'CANCELLED')
      )
    )
    """,
    "CREATE UNIQUE INDEX ux_whatsapp_campaigns_idempotency"
    " ON whatsapp_campaigns(tenant_id, idempotency_key)",
    "CREATE UNIQUE INDEX ux_whatsapp_campaigns_gateway"
    " ON whatsapp_campaigns(tenant_id, gateway_campaign_id)"
    " WHERE gateway_campaign_id IS NOT NULL",
    "CREATE INDEX ix_whatsapp_campaigns_tenant"
    " ON whatsapp_campaigns(tenant_id, status, created_at DESC)",
    "CREATE INDEX ix_whatsapp_campaigns_representative"
    " ON whatsapp_campaigns(representative_user_id, created_at DESC)",
    """
    CREATE TABLE whatsapp_campaign_recipients (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      campaign_id uuid NOT NULL REFERENCES whatsapp_campaigns(id),
      customer_id uuid NOT NULL REFERENCES customers(id),
      contact_id uuid REFERENCES customer_contacts(id),
      representative_user_id uuid REFERENCES users(id),
      recipient_snapshot jsonb NOT NULL,
      status whatsapp_campaign_recipient_status NOT NULL DEFAULT 'PENDING',
      excluded_reason text,
      failure_reason text,
      gateway_message_id text,
      response_interaction_id uuid REFERENCES customer_interactions(id),
      status_updated_at timestamptz NOT NULL DEFAULT now(),
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT ck_wcr_exclusion CHECK (
        (status = 'EXCLUDED' AND excluded_reason IS NOT NULL)
        OR (status <> 'EXCLUDED' AND excluded_reason IS NULL)
      ),
      CONSTRAINT ck_wcr_contact CHECK (
        contact_id IS NOT NULL OR status = 'EXCLUDED'
      ),
      CONSTRAINT ck_wcr_failure CHECK (
        failure_reason IS NULL OR status = 'FAILED'
      )
    )
    """,
    "CREATE UNIQUE INDEX ux_wcr_contact"
    " ON whatsapp_campaign_recipients(campaign_id, customer_id, contact_id)"
    " WHERE contact_id IS NOT NULL",
    "CREATE UNIQUE INDEX ux_wcr_customer_without_contact"
    " ON whatsapp_campaign_recipients(campaign_id, customer_id)"
    " WHERE contact_id IS NULL",
    "CREATE UNIQUE INDEX ux_wcr_gateway_message"
    " ON whatsapp_campaign_recipients(tenant_id, gateway_message_id)"
    " WHERE gateway_message_id IS NOT NULL",
    "CREATE INDEX ix_whatsapp_campaign_recipients_campaign"
    " ON whatsapp_campaign_recipients(campaign_id)",
    "CREATE INDEX ix_wcr_customer"
    " ON whatsapp_campaign_recipients(customer_id, created_at DESC)",
)

# A reversão recusa apagar campanha que saiu do rascunho: confirmada ou em
# andamento, ela é o registro do que foi aprovado e do que o canal executou.
# Rascunhos e cancelamentos somem sem perda — a trilha de auditoria fica.
_DOWNGRADE = (
    """
    DO $$
    DECLARE
      aprovadas bigint;
    BEGIN
      SELECT count(*) INTO aprovadas
        FROM whatsapp_campaigns
       WHERE status NOT IN ('DRAFT', 'CANCELLED');
      IF aprovadas > 0 THEN
        RAISE EXCEPTION
          'ha % campanhas que sairam do rascunho; apagar as tabelas perderia o que foi aprovado',
          aprovadas;
      END IF;
    END $$
    """,
    "DROP TABLE whatsapp_campaign_recipients",
    "DROP TABLE whatsapp_campaigns",
    "DROP TYPE whatsapp_campaign_recipient_status",
    "DROP TYPE whatsapp_campaign_status",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
