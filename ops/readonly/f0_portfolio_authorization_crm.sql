-- F0 — Autorização por carteira: levantamento do CRM (SOMENTE LEITURA)
--
-- Onde executar
--   PostgreSQL do CRM, banco `crm` (em produção: serviço CapRover
--   `srv-captain--postgres`). No host da VPS:
--     docker exec -i $(docker ps -q -f name=srv-captain--postgres) \
--       psql -U crm -d crm -v ON_ERROR_STOP=1 -f - < f0_portfolio_authorization_crm.sql
--   ou cole o conteúdo numa sessão `psql -U crm -d crm`. A transação abaixo é
--   READ ONLY: o próprio Postgres recusa qualquer escrita dentro dela.
--
-- Dados pessoais
--   Telefones aparecem só com os 4 últimos dígitos. Clientes aparecem por nome
--   apenas em C4 (titulares fora da regra), que é a lista a corrigir.
--
-- O que devolver
--   O resultado de C1 a C7. C1 deve casar com G2 do Gateway
--   (`gateway_line_reference` e `users.public_ref` = `representative_reference`).

BEGIN TRANSACTION READ ONLY;

-- C1. Conexões de linha por representante.
SELECT
  c.id,
  u.full_name,
  u.email,
  u.role,
  u.active             AS user_active,
  u.public_ref         AS user_public_ref,
  c.status,
  c.last_gateway_status,
  c.failure_code,
  c.gateway_line_reference,
  c.display_phone_number,
  c.connected_at,
  c.created_at
FROM representative_whatsapp_connections AS c
JOIN users AS u ON u.id = c.representative_user_id
ORDER BY c.created_at;

-- C2. Mesma referência em mais de uma conexão (a F1 nega: LINE_UNKNOWN).
SELECT gateway_line_reference, COUNT(*) AS connections
FROM representative_whatsapp_connections
WHERE gateway_line_reference IS NOT NULL
GROUP BY gateway_line_reference
HAVING COUNT(*) > 1;

-- C3. Clientes ativos por situação do titular.
SELECT
  COALESCE(u.role::text, 'SEM_TITULAR') AS owner_role,
  u.active                              AS owner_active,
  COUNT(*)                              AS customers
FROM customers AS c
LEFT JOIN users AS u ON u.id = c.owner_user_id
WHERE c.active
GROUP BY 1, 2
ORDER BY 1, 2;

-- C4. Clientes ativos cujo titular não é representante ativo. Pela regra,
-- passam a ser negados; precisam de reatribuição antes da F4.
SELECT
  c.legal_name,
  c.trade_name,
  u.full_name AS owner_name,
  u.email     AS owner_email,
  u.role      AS owner_role,
  u.active    AS owner_active
FROM customers AS c
JOIN users AS u ON u.id = c.owner_user_id
WHERE c.active
  AND (u.role::text <> 'REPRESENTATIVE' OR NOT u.active)
ORDER BY u.full_name, c.legal_name;

-- C5. Nomes de usuário repetidos (insumo da F5).
SELECT lower(full_name) AS normalized_name, COUNT(*) AS users,
       string_agg(email || ' (' || role::text || ')', ', ' ORDER BY email) AS accounts
FROM users
GROUP BY lower(full_name)
HAVING COUNT(*) > 1;

-- C6. Telefone que é de usuário e de contato ao mesmo tempo (AMBIGUOUS_PHONE).
SELECT
  '***' || right(u.whatsapp_e164, 4) AS phone_suffix,
  u.email,
  u.role,
  u.active   AS user_active,
  cc.active  AS contact_active,
  cu.active  AS customer_active
FROM users AS u
JOIN customer_contacts AS cc
  ON cc.tenant_id = u.tenant_id AND cc.whatsapp_e164 = u.whatsapp_e164
JOIN customers AS cu ON cu.id = cc.customer_id;

-- C7. Telefones fora da forma canônica. A decisão busca só pela forma
-- canônica; estes contatos seriam CONTACT_NOT_FOUND.
SELECT 'customer_contacts' AS source, '***' || right(whatsapp_e164, 4) AS phone_suffix, active
FROM customer_contacts
WHERE whatsapp_e164 !~ '^\+[1-9][0-9]{7,14}$'
   OR whatsapp_e164 ~ '^\+55[1-9][0-9][6-9][0-9]{7}$'
UNION ALL
SELECT 'users', '***' || right(whatsapp_e164, 4), active
FROM users
WHERE whatsapp_e164 IS NOT NULL
  AND (whatsapp_e164 !~ '^\+[1-9][0-9]{7,14}$'
       OR whatsapp_e164 ~ '^\+55[1-9][0-9][6-9][0-9]{7}$');

ROLLBACK;
