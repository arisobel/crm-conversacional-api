# CRM Conversacional API

API de domínio e persistência para o CRM conversacional integrado ao WhatsApp Gateway.

## Objetivo do MVP

Transformar catálogo, produtos preferenciais, tabelas de preço e condições comerciais em ofertas auditáveis para WhatsApp, com aprovação humana antes do envio.

## Limites de responsabilidade

- **WhatsApp Gateway:** integração com Meta, roteamento e entrega.
- **CRM Conversacional API:** clientes, catálogo, preços, regras, ofertas, conversas e persistência.
- **LLM:** interpretação e redação; nunca é fonte de preço nem executa SQL livre.

## Fontes principais

- [Índice da documentação](docs/README.md)
- [Escopo do MVP](docs/01_definition/mvp-scope.md)
- [Arquitetura](docs/01_definition/architecture.md)
- [Modelo de domínio](docs/01_definition/domain-model.md)
- [Decisões](docs/00_meta/DECISIONS.md)
- [Backlog](docs/00_meta/BACKLOG.md)
- [DDL PostgreSQL](db/migrations/0001_initial.sql)
- [Contrato OpenAPI](openapi/crm-api.yaml)

## Estado

Estrutura inicial para revisão. A stack executável será escolhida e implementada no próximo baby-step.
