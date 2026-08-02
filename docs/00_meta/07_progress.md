# Progresso central

Atualizado em: 2026-07-29

## Estado atual

**Fase ativa:** F1 — catálogo, tabela vigente e consulta por produto.

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

## Em andamento

- Consulta específica de produto no WhatsApp, com busca determinística na tabela vigente.

## Próximo baby-step

Implementar a busca assinada de itens da tabela vigente por SKU, nome comercial,
especificação e família; em seguida, expor o comando `produto <termo>` no Gateway.

## Evidências

- DDL: `db/migrations/0001_initial.sql`
- OpenAPI: `openapi/crm-api.yaml`
- Critérios: `docs/50_validation/ACCEPTANCE_CRITERIA.md`
- Operação F1: `docs/40_delivery/F1_PRICE_LIST_GATEWAY.md`
