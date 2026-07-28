BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE availability_status AS ENUM (
  'AVAILABLE','OUT_OF_STOCK','SUSPENDED','FUTURE_ARRIVAL','CONSULT'
);
CREATE TYPE price_list_status AS ENUM ('DRAFT','ACTIVE','EXPIRED','CANCELLED');
CREATE TYPE adjustment_type AS ENUM ('PERCENT_DISCOUNT','PERCENT_SURCHARGE','AMOUNT_PER_KG');
CREATE TYPE commercial_term_type AS ENUM ('PAYMENT','MINIMUM_QUANTITY','OTHER');
CREATE TYPE offer_status AS ENUM (
  'DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SENT','FAILED','CANCELLED'
);
CREATE TYPE message_direction AS ENUM ('INBOUND','OUTBOUND');
CREATE TYPE delivery_status AS ENUM ('PENDING','SENT','DELIVERED','READ','FAILED');

CREATE TABLE tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  slug text NOT NULL UNIQUE,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE customers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  legal_name text NOT NULL,
  trade_name text,
  document_number text,
  state_code char(2) NOT NULL CHECK (state_code ~ '^[A-Z]{2}$'),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, document_number)
);

CREATE TABLE customer_contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  customer_id uuid NOT NULL REFERENCES customers(id),
  name text NOT NULL,
  whatsapp_e164 text NOT NULL CHECK (whatsapp_e164 ~ '^\+[1-9][0-9]{7,14}$'),
  is_primary boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, whatsapp_e164)
);

CREATE UNIQUE INDEX ux_primary_contact_per_customer
  ON customer_contacts(customer_id) WHERE is_primary AND active;

CREATE TABLE product_families (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  name text NOT NULL,
  display_order integer NOT NULL DEFAULT 0,
  active boolean NOT NULL DEFAULT true,
  UNIQUE (tenant_id, name)
);

CREATE TABLE products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  family_id uuid NOT NULL REFERENCES product_families(id),
  sku text NOT NULL,
  commercial_name text NOT NULL,
  specification text,
  unit text NOT NULL DEFAULT 'KG' CHECK (unit IN ('KG')),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sku)
);

CREATE TABLE customer_preferred_products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  customer_id uuid NOT NULL REFERENCES customers(id),
  product_id uuid NOT NULL REFERENCES products(id),
  customer_alias text,
  display_order integer NOT NULL DEFAULT 0,
  include_by_default boolean NOT NULL DEFAULT true,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (customer_id, product_id)
);

CREATE TABLE price_lists (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  name text NOT NULL,
  reference_month date NOT NULL CHECK (reference_month = date_trunc('month', reference_month)::date),
  valid_from timestamptz NOT NULL,
  valid_until timestamptz,
  currency char(3) NOT NULL DEFAULT 'BRL',
  base_tax_rate numeric(6,3),
  status price_list_status NOT NULL DEFAULT 'DRAFT',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (valid_until IS NULL OR valid_until > valid_from),
  CHECK (base_tax_rate IS NULL OR base_tax_rate BETWEEN 0 AND 100),
  UNIQUE (tenant_id, name, reference_month)
);

CREATE INDEX ix_price_lists_current
  ON price_lists(tenant_id, status, valid_from, valid_until);

CREATE TABLE price_list_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  price_list_id uuid NOT NULL REFERENCES price_lists(id) ON DELETE CASCADE,
  product_id uuid NOT NULL REFERENCES products(id),
  base_price numeric(14,4) NOT NULL CHECK (base_price >= 0),
  availability availability_status NOT NULL DEFAULT 'CONSULT',
  expected_arrival_date date,
  available_quantity_kg numeric(14,3) CHECK (available_quantity_kg IS NULL OR available_quantity_kg >= 0),
  arrival_note text,
  item_tax_rate numeric(6,3) CHECK (item_tax_rate IS NULL OR item_tax_rate BETWEEN 0 AND 100),
  notes text,
  UNIQUE (price_list_id, product_id)
);

CREATE TABLE commercial_terms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  price_list_id uuid NOT NULL REFERENCES price_lists(id) ON DELETE CASCADE,
  customer_id uuid REFERENCES customers(id),
  term_type commercial_term_type NOT NULL,
  code text NOT NULL,
  adjustment adjustment_type NOT NULL,
  adjustment_value numeric(14,4) NOT NULL CHECK (adjustment_value >= 0),
  minimum_quantity_kg numeric(14,3),
  maximum_payment_days integer,
  priority integer NOT NULL DEFAULT 100,
  valid_from timestamptz,
  valid_until timestamptz,
  active boolean NOT NULL DEFAULT true,
  CHECK (minimum_quantity_kg IS NULL OR minimum_quantity_kg >= 0),
  CHECK (maximum_payment_days IS NULL OR maximum_payment_days >= 0),
  CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from)
);

CREATE TABLE freight_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  price_list_id uuid NOT NULL REFERENCES price_lists(id) ON DELETE CASCADE,
  customer_id uuid REFERENCES customers(id),
  state_code char(2) NOT NULL CHECK (state_code ~ '^[A-Z]{2}$'),
  amount_per_kg numeric(14,4) NOT NULL CHECK (amount_per_kg >= 0),
  priority integer NOT NULL DEFAULT 100,
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE tax_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  price_list_id uuid NOT NULL REFERENCES price_lists(id) ON DELETE CASCADE,
  product_id uuid REFERENCES products(id),
  customer_id uuid REFERENCES customers(id),
  state_code char(2),
  tax_rate numeric(6,3) NOT NULL CHECK (tax_rate BETWEEN 0 AND 100),
  adjustment_per_kg numeric(14,4) NOT NULL DEFAULT 0,
  priority integer NOT NULL DEFAULT 100,
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  contact_id uuid NOT NULL REFERENCES customer_contacts(id),
  channel text NOT NULL DEFAULT 'WHATSAPP' CHECK (channel = 'WHATSAPP'),
  external_thread_id text,
  opened_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz,
  CHECK (closed_at IS NULL OR closed_at >= opened_at)
);

CREATE TABLE inbound_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  external_event_id text NOT NULL,
  received_at timestamptz NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  processed_at timestamptz,
  processing_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, external_event_id)
);

CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  conversation_id uuid NOT NULL REFERENCES conversations(id),
  direction message_direction NOT NULL,
  external_message_id text,
  message_type text NOT NULL,
  body text,
  raw_payload jsonb,
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, external_message_id)
);

CREATE TABLE offers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  customer_id uuid NOT NULL REFERENCES customers(id),
  contact_id uuid REFERENCES customer_contacts(id),
  conversation_id uuid REFERENCES conversations(id),
  price_list_id uuid NOT NULL REFERENCES price_lists(id),
  status offer_status NOT NULL DEFAULT 'DRAFT',
  destination_state char(2) NOT NULL CHECK (destination_state ~ '^[A-Z]{2}$'),
  currency char(3) NOT NULL DEFAULT 'BRL',
  payment_term_code text,
  message_preview text,
  final_message text,
  approved_by text,
  approved_at timestamptz,
  sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((status NOT IN ('APPROVED','SENT')) OR approved_at IS NOT NULL),
  CHECK (status <> 'SENT' OR sent_at IS NOT NULL)
);

CREATE INDEX ix_offers_customer_created ON offers(customer_id, created_at DESC);

CREATE TABLE offer_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  offer_id uuid NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
  product_id uuid NOT NULL REFERENCES products(id),
  display_order integer NOT NULL DEFAULT 0,
  display_name text NOT NULL,
  quantity_kg numeric(14,3),
  base_price numeric(14,4) NOT NULL CHECK (base_price >= 0),
  discount_amount_per_kg numeric(14,4) NOT NULL DEFAULT 0,
  surcharge_amount_per_kg numeric(14,4) NOT NULL DEFAULT 0,
  freight_amount_per_kg numeric(14,4) NOT NULL DEFAULT 0,
  tax_rate numeric(6,3),
  final_price_per_kg numeric(14,4) NOT NULL CHECK (final_price_per_kg >= 0),
  availability availability_status NOT NULL,
  expected_arrival_date date,
  availability_note text,
  calculation_snapshot jsonb NOT NULL,
  CHECK (quantity_kg IS NULL OR quantity_kg > 0),
  CHECK (discount_amount_per_kg >= 0 AND surcharge_amount_per_kg >= 0 AND freight_amount_per_kg >= 0),
  UNIQUE (offer_id, product_id)
);

CREATE TABLE outbound_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  offer_id uuid REFERENCES offers(id),
  conversation_id uuid NOT NULL REFERENCES conversations(id),
  idempotency_key text NOT NULL,
  gateway_message_id text,
  status delivery_status NOT NULL DEFAULT 'PENDING',
  payload jsonb NOT NULL,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  delivered_at timestamptz,
  UNIQUE (tenant_id, idempotency_key),
  UNIQUE (tenant_id, gateway_message_id)
);

COMMIT;
