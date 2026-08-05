# Progresso central

Atualizado em: 2026-08-05

## Estado atual

**Fase ativa:** F5 — portal do representante. R0, R1 e R2 implementados; R3 é o
próximo.

**Mudança de direção em 2026-08-04:** o produto passa a ser um CRM operado por
representantes comerciais; o WhatsApp vira canal, não interface primária. Ver
[direção do produto](../10_product/REPRESENTATIVE_DIRECTION.md), ADRs 013 a 016
e o [plano de entrega F5](../40_delivery/F5_REPRESENTATIVE_PORTAL.md).

O que estava em andamento — consulta específica de produto no WhatsApp — não foi
cancelado, mas sai da frente da fila: entra depois de R3, quando o preço já
vier de `price_entries`.

## Concluído

- Separação entre WhatsApp Gateway e CRM Conversacional API.
- Modelo lógico inicial e migração PostgreSQL.
- Contrato OpenAPI inicial.
- Reorganização documental conforme a orquestração do projeto.
- Decisões centrais: competência mensal em colunas, cálculo determinístico, oferta imutável e aprovação humana.
- Stack F0 definida: Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2 assíncrono,
  asyncpg, Alembic, pytest, Ruff, Docker Compose e PostgreSQL 16.
- Serviço FastAPI com configuração por ambiente, `GET /health`, `GET /ready` e busca
  interna de cliente ativo por WhatsApp.
- Modelos ORM iniciais de tenant, cliente e contato; migração Alembic executável que
  aplica o DDL PostgreSQL aprovado.
- Contrato de escopo de tenant e HMAC com o WhatsApp Gateway registrado.
- Leitura interna da tabela `ACTIVE` por contato WhatsApp, com disponibilidade explícita
  e valores decimais estruturados, sem cálculo comercial implícito.
- Carga CSV revisada da tabela especial de 20/07/2026, ativada em produção para o tenant
  `empresa-textil`.
- Integração publicada no Gateway: o comando `tabela` consulta a lista vigente por HMAC,
  agrupa itens por família e exibe preço-base, indisponibilidade e chegada prevista.
- Especificação técnica exposta na resposta para distinguir itens com o mesmo nome
  comercial, como os itens Rubberflex.

- Planejamento da direção de CRM de representantes: direção do produto,
  modelo-alvo, plano de entrega R0–R6 e ADRs 013 a 016.
- **R0 — fundação de identidade.** Migração `0003` com `users`, `user_sessions`,
  `audit_log` e o enum `user_role`. Argon2id, política de senha, bloqueio por
  conta após falhas, limitador de tentativas em janela, sessão com estado no
  servidor (cookie httpOnly, janela deslizante e teto absoluto), autorização por
  papel separada do HMAC do Gateway, trilha de auditoria de login e CLI
  `python -m crm_api.admin_cli create-user`.

- **R1 — representante e carteira.** Migração `0004` com
  `customers.owner_user_id` e `customer_assignment_history`. CRUD de usuários do
  portal restrito a `ADMIN`, designação/transferência/remoção de titular com
  histórico append-only, `GET /admin/customers` e `GET /admin/me/customers` com
  escopo aplicado no repositório, e filtros por UF, produto preferido, situação,
  titularidade e busca textual.

- **R2 — cadastro comercial e localidades.** Migração `0005` com
  `customer_locations` e backfill de uma localidade padrão por cliente. CRUD de
  cliente, contatos e localidades pelo portal, com UF validada contra as 27
  unidades federativas, telefone normalizado em E.164 e único por tenant, e
  unicidade da localidade padrão e do contato principal garantida por índice
  parcial no banco. O escopo foi ampliado além do plano: o CRUD de cliente e
  contatos não tinha etapa dona, e sem ele cadastrar cliente ainda exigiria SQL.

## Em andamento

- Nada em implementação. Aguardando início de R3.

## Próximo baby-step

R3 — migração `0006` com `price_entries` e `price_entry_revisions`, publicação
de lote com `UPSERT` transacional e backfill da tabela ativa de 20/07/2026 para
a competência `2026-07`. É a etapa de maior risco: há dado em produção e o
Gateway consome a rota de tabela vigente.

Em paralelo, obter a confirmação contábil de Q1 e Q2 (ICMS embutido no
preço-base e fórmula de conversão entre UFs), que bloqueiam R4.

## Pendências abertas

- As migrações `0003`, `0004` e `0005` **não foram executadas contra
  PostgreSQL**: não há Docker nem banco disponível no ambiente de
  desenvolvimento atual. A cadeia de revisões foi validada
  (`0005_customer_locations` é head) e o esquema equivalente roda nos testes
  sobre SQLite, mas a primeira aplicação real precisa de verificação. A `0005`
  é a que mais merece atenção: além do DDL, ela roda um `INSERT ... SELECT` de
  backfill sobre `customers`.
- `CRM_SESSION_COOKIE_SECURE` precisa permanecer `true` em produção; só os
  testes o desligam.
- O limitador de login tem estado em processo. Com mais de uma réplica, ele
  precisa migrar para armazenamento compartilhado; o bloqueio por conta em
  `users.locked_until` é o controle que já atravessa réplicas.
- Nenhum cliente de produção tem titular. A carteira só passa a existir quando
  um administrador designar os titulares pelo portal.
- O filtro por data da última interação continua pendente até R5.

## Evidências

- DDL: `db/migrations/0001_initial.sql`
- OpenAPI: `openapi/crm-api.yaml`
- Critérios: `docs/50_validation/ACCEPTANCE_CRITERIA.md`
- Operação F1: `docs/40_delivery/F1_PRICE_LIST_GATEWAY.md`
