# Progresso central

Atualizado em: 2026-07-28

## Estado atual

**Fase ativa:** F0 — fundação documental e técnica do MVP.

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

## Em andamento

- Validação da migração Alembic em PostgreSQL real e do Compose local.

## Próximo baby-step

Subir o Compose, aplicar a migração em PostgreSQL e validar a primeira chamada assinada
do Gateway para busca de contato por WhatsApp.

## Evidências

- DDL: `db/migrations/0001_initial.sql`
- OpenAPI: `openapi/crm-api.yaml`
- Critérios: `docs/50_validation/ACCEPTANCE_CRITERIA.md`
