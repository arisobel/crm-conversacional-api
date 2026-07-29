# Progresso central

Atualizado em: 2026-07-29

## Estado atual

**Fase ativa:** F1 — catálogo e leitura estruturada da tabela vigente.

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

## Em andamento

- Carga revisável da tabela especial de 20/07/2026 e conferência humana antes de ativá-la.

## Próximo baby-step

Preparar a carga CSV da tabela especial, revisá-la com o comercial, ativar somente a
tabela conferida e validar a leitura assinada pelo Gateway.

## Evidências

- DDL: `db/migrations/0001_initial.sql`
- OpenAPI: `openapi/crm-api.yaml`
- Critérios: `docs/50_validation/ACCEPTANCE_CRITERIA.md`
