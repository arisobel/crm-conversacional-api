-- Executar somente contra banco de teste migrado; não persiste dados de teste.
BEGIN;
DO $$
DECLARE
  a uuid := gen_random_uuid();
  b uuid := gen_random_uuid();
  representative uuid := gen_random_uuid();
  actual boolean;
BEGIN
  INSERT INTO tenants (id, name, slug) VALUES
    (a, 'Teste A', 'assistant-test-a'), (b, 'Teste B', 'assistant-test-b');
  INSERT INTO users (id, tenant_id, full_name, email, password_hash, role, public_ref)
    VALUES (representative, a, 'Teste', 'test@example.com', 'unused',
            'REPRESENTATIVE', '1234567890abcdef12345678');
  INSERT INTO assistant_organization_settings (tenant_id) VALUES (a) RETURNING enabled INTO actual;
  IF actual IS DISTINCT FROM false THEN RAISE EXCEPTION 'organization default'; END IF;
  INSERT INTO assistant_representative_settings (tenant_id, user_id)
    VALUES (a, representative) RETURNING enabled INTO actual;
  IF actual IS DISTINCT FROM false THEN RAISE EXCEPTION 'representative default'; END IF;
  BEGIN
    INSERT INTO assistant_representative_settings (tenant_id, user_id) VALUES (b, representative);
    RAISE EXCEPTION 'cross-tenant representative accepted';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
  INSERT INTO assistant_representative_capabilities (tenant_id, user_id, capability_id)
    VALUES (a, representative, 'CRM_REP_SEARCH_PRICE_ITEMS');
  BEGIN
    INSERT INTO assistant_representative_capabilities (tenant_id, user_id, capability_id)
      VALUES (a, representative, 'CRM_REP_SEARCH_PRICE_ITEMS');
    RAISE EXCEPTION 'duplicate capability accepted';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
  DELETE FROM assistant_representative_settings WHERE tenant_id = a AND user_id = representative;
  IF EXISTS (SELECT 1 FROM assistant_representative_capabilities WHERE tenant_id = a)
    THEN RAISE EXCEPTION 'capability cascade failed'; END IF;
END $$;
ROLLBACK;
