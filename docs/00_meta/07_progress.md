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

## Em andamento

- Revisão desta reorganização por Pull Request.

## Próximo baby-step

Escolher a stack da API e entregar um serviço executável com conexão PostgreSQL, migração, endpoint de saúde, busca de cliente por WhatsApp e testes automatizados.

## Evidências

- DDL: `db/migrations/0001_initial.sql`
- OpenAPI: `openapi/crm-api.yaml`
- Critérios: `docs/50_validation/ACCEPTANCE_CRITERIA.md`
