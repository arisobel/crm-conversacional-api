# Progresso central

Atualizado em: 2026-08-06

## Estado atual

**Fase ativa:** F5 — portal do representante. **R0 a R6 implementados.**
Verificado em produção até R2; as migrações `0006`, `0007` e `0008` ainda não
foram implantadas.

O plano F5 está concluído do lado do CRM. O único item de R5 que permanece
aberto vive em outro repositório: o push do Gateway.

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

- **R6a — telas de cadastro do portal.** Antecipada: não dependia de R3–R5 e
  era o que faltava para popular a base sem PowerShell. Portal server-rendered
  com Jinja2 sob `/portal`, na mesma origem da API (ADR-017, que revisa a
  recomendação anterior de aplicação separada). Login, carteira com filtros,
  ficha do cliente com contatos e localidades, transferência de titular e tela
  de representantes. Proteção CSRF por double-submit cookie.

## Verificado em produção

- Migrações `0003`, `0004` e `0005` aplicadas; `alembic current` em
  `0005_customer_locations`. As quatro tabelas novas existem e o backfill da
  `0005` criou a localidade `Principal` para os dois clientes, com a UF
  preservada.
- Login e sessão do portal funcionando sobre HTTPS: `POST /admin/auth/login`
  emite o cookie e `GET /admin/auth/me` o aceita.

- **R3 — preço por competência.** Migração `0006` com `price_entries` e
  `price_entry_revisions`. Publicação de lote com `UPSERT` e revisão por linha,
  idempotente ao republicar. A leitura consumida pelo Gateway passou a vir de
  `price_entries` com o contrato de resposta intacto — `tests/test_api.py` teve
  só o fixture alterado e todas as asserções continuam passando.
- **R4 — motor de ICMS.** Migração `0007` com `tenants.origin_state_code` e
  `icms_rules`. Resolução por especificidade em seis níveis, com erro explícito
  em empate e em ausência de regra. Conversão com trace por item e fórmula
  selecionável em `CRM_ICMS_CONVERSION_MODE`. Rota de lista resolvida por
  cliente e localidade, e CRUD da matriz restrito a `ADMIN`.

- **R5 — histórico de interações.** Migração `0008` com `customer_interactions`.
  Ingestão em lote por HMAC, idempotente por `(tenant, source, external_ref)`,
  com savepoint por item para que um evento recusado não derrube o lote.
  Timeline paginada com escopo de carteira, filtro de carteira por última
  interação e expurgo auditado que **recusa rodar sem política de retenção**.

- **R6b — telas dependentes.** Tabela do mês com publicação e revisões, matriz
  de ICMS, lista de preço resolvida por cliente com trilha e exportação CSV,
  timeline e produtos preferidos na ficha. Cabeçalhos contra clickjacking em
  toda resposta e `/docs` desligado por padrão.

## Em andamento

- Nada em implementação. O plano F5 está concluído do lado do CRM.

## Próximo baby-step

Implantar `0006`, `0007` e `0008` em produção, com atenção ao backfill da
`0006`, que interrompe se encontrar dois preços ativos para o mesmo produto e
mês. As três sobem juntas na mesma transação: se a `0006` abortar, nenhuma é
aplicada.

Depois disso, três coisas que dependem de decisão e não de código:

1. **Confirmar Q1 e Q2** antes de qualquer preço convertido ir a um cliente. O
   sistema não estima: sem matriz carregada ele falha. Mas com a matriz
   carregada e a fórmula errada, ele produz números plausíveis e incorretos.
2. **Confirmar Q3** e configurar `CRM_INTERACTION_RETENTION_DAYS`. Sem ela, nada
   é apagado — o que é seguro, mas não é uma política.
3. **Implementar o push no Gateway.** Sem ele a timeline existe e fica vazia.

## Pendências abertas

- As migrações `0006`, `0007` e `0008` **ainda não foram implantadas**. Nenhuma
  migração é executada contra PostgreSQL no ambiente de desenvolvimento — não há
  Docker nem banco aqui; a validação é a cadeia de revisões
  (`0008_customer_interactions` é head) e o esquema equivalente sobre SQLite nos
  testes.
- O push do Gateway **não foi implementado**: ele vive em outro repositório. O
  contrato está em
  [F5_INTERACTION_PUSH_CONTRACT](../40_delivery/F5_INTERACTION_PUSH_CONTRACT.md).
  Até ele existir, a timeline da ficha fica vazia — a tela funciona, os dados não
  chegam.
- `CRM_EXPOSE_API_DOCS` passou a valer `false` por padrão. Quem usava `/docs` em
  produção precisa ligá-lo explicitamente, ou passar a ler
  `openapi/crm-api.yaml`.
- Q3 sem resposta: `CRM_INTERACTION_RETENTION_DAYS` não está configurada e o
  expurgo recusa rodar. Nada é apagado enquanto isso.
- A `0006` é a mais delicada de todas até agora: ela verifica conflitos antes de
  gravar e **aborta a transação inteira** se encontrar duas tabelas `ACTIVE` com
  o mesmo produto e competência, em vez de resolver por "último vence".
- **Q1 e Q2 continuam sem resposta contábil.** R4 foi implementada assim mesmo,
  com a fórmula selecionável e sem estimativa implícita, mas a confirmação
  precisa vir antes de qualquer preço convertido chegar a um cliente.
- `CRM_SESSION_COOKIE_SECURE` precisa permanecer `true` em produção; só os
  testes o desligam.
- O limitador de login tem estado em processo. Com mais de uma réplica, ele
  precisa migrar para armazenamento compartilhado; o bloqueio por conta em
  `users.locked_until` é o controle que já atravessa réplicas.
- Nenhum cliente de produção tem titular. A carteira só passa a existir quando
  um administrador designar os titulares pelo portal.

## Evidências

- DDL: `db/migrations/0001_initial.sql`
- OpenAPI: `openapi/crm-api.yaml`
- Critérios: `docs/50_validation/ACCEPTANCE_CRITERIA.md`
- Operação F1: `docs/40_delivery/F1_PRICE_LIST_GATEWAY.md`
