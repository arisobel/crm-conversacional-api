# Problemas conhecidos

Registre aqui somente problemas observados no código, testes, contratos ou comportamento do produto.

## Abertos

- `ix_product_compositions_product(product_id)` é redundante com
  `ux_product_composition(product_id, fiber_id)`: um btree já atende consulta pelo
  prefixo da chave. Custa escrita e não paga leitura. Fica como está — a `0014` já
  foi publicada, e migração publicada não se emenda por ganho nulo. Se um dia
  houver outra migração mexendo em `product_compositions`, esse índice sai junto.
- `index=True` nos modelos não produz índice em produção. O banco de produção é
  construído por migração, nunca por `Base.metadata.create_all`, e a declaração
  do modelo só materializa no SQLite da suíte. É documentação que não corresponde
  ao banco: ao ler um modelo, o índice real está na migração correspondente.
  Medido na `0014`, cujo modelo declara `index=True` em `tenant_id`, `product_id`
  e `fiber_id` e cuja tabela em produção tem exatamente `product_compositions_pkey`,
  `ix_product_compositions_fiber`, `ix_product_compositions_product` e
  `ux_product_composition`.
- O `CHECK` de UF de `customers` tem nomes diferentes nos dois lados: a `0001`
  criou a restrição sem nome e o PostgreSQL a batizou de
  `customers_state_code_check`, enquanto o modelo a declara como
  `ck_customers_state`. O **texto** é idêntico, e é isso que
  `ops/ci/check_pg_schema.py` compara. Renomear exigiria migração, e o nome não
  aparece em nenhuma mensagem que o produto mostre.
- O SQLite da suíte não verifica chave estrangeira (`PRAGMA foreign_keys` nasce
  desligado), então um cenário mal ordenado passa em SQLite e quebra em
  PostgreSQL. O `persist` do `conftest` neutraliza isso gravando tabela a tabela
  na ordem topológica, mas a lacuna continua existindo para quem escrever um
  cenário novo com `session.add_all` direto. O job `tests-postgres` é quem pega.
- O contrato OpenAPI ainda não foi validado por ferramenta automatizada.
- O repositório está público; não devem ser adicionados segredos ou dados comerciais reais.

## Resolvidos

- A migração PostgreSQL ainda não havia sido executada em uma instância real;
  em 2026-08-23 a cadeia `0001 → 0014` subiu limpa contra PostgreSQL 16, com
  `downgrade -1` e novo `upgrade head`, e o job `migrations` da CI passou a
  repetir isso a cada push.
- Os modelos ORM não eram criáveis em PostgreSQL: `customers` declarava
  `CHECK (state_code GLOB '[A-Z][A-Z]')`, e `GLOB` só existe no SQLite
  (`asyncpg.exceptions.PostgresSyntaxError: syntax error at or near "GLOB"`).
  Resolvido na fatia 1.5 com `CheckConstraint(...).ddl_if(dialect=...)`, uma
  expressão por engine, com o texto da versão PostgreSQL igual ao da `0001`.
- As colunas de UF eram `String(2)` no modelo e `char(2)` nas migrações. A
  diferença mudava o texto que o PostgreSQL renderiza para o `CHECK`
  (`((state_code)::text ~ ...)` contra `(state_code ~ ...)`) e impedia comparar
  modelo e produção. Alinhadas para `CHAR(2)` na fatia 1.5.
- A documentação de orquestração continha referências indevidas ao projeto `pwa-fair`; corrigida na reorganização documental de 2026-07-28.
- A busca por WhatsApp não tinha escopo de tenant; corrigida no corte F0 por `X-Tenant-Slug` autenticado via HMAC (ADR-008).
- O OpenAPI não descrevia `GET /ready`; corrigido no corte F0.
