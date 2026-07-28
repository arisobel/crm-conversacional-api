# CRM Conversacional API

API de domínio e persistência do CRM integrado ao WhatsApp Gateway.

## Objetivo

Gerar ofertas comerciais personalizadas, corretas e auditáveis com catálogo, produtos preferenciais, tabela vigente, regras determinísticas e aprovação humana.

## Limites

- **WhatsApp Gateway:** Meta Cloud API, roteamento e entrega.
- **CRM API:** clientes, catálogo, preços, ofertas, conversas e persistência.
- **LLM:** interpretação e redação; nunca fonte de preço ou SQL livre.

## Documentação

- [Índice](docs/README.md)
- [Orquestração](docs/00_meta/AGENT_SKILL_ORCHESTRATION.md)
- [Progresso](docs/00_meta/07_progress.md)
- [Roadmap](docs/10_product/MVP_ROADMAP.md)
- [Regras de negócio](docs/20_domain/BUSINESS_RULES.md)
- [Arquitetura](docs/30_architecture/ARCHITECTURE.md)
- [DDL PostgreSQL](db/migrations/0001_initial.sql)
- [OpenAPI](openapi/crm-api.yaml)

## Estado

F0 — fundação documental e técnica. A stack executável é o próximo baby-step.
