# Documentação

Memória operacional do CRM Conversacional API.

## Estrutura

| Diretório | Função |
|---|---|
| `00_meta` | Orquestração, progresso, decisões, backlog e issues |
| `10_product` | Manifesto e roadmap do produto |
| `20_domain` | Regras e modelo do domínio |
| `30_architecture` | Arquitetura e contrato da API |
| `40_delivery` | Blueprints das fases de entrega |
| `50_validation` | Critérios e evidências de validação |

## Leitura obrigatória antes de implementar

1. [Orquestração](00_meta/AGENT_SKILL_ORCHESTRATION.md)
2. [Progresso](00_meta/07_progress.md)
3. [Backlog](00_meta/09_backlog.md)
4. [Manifesto](10_product/BUSINESS_FEATURE_MANIFESTO.md)
5. [Roadmap](10_product/MVP_ROADMAP.md)
6. [Contrato do projeto](00_meta/AGENT_SKILL_PROJECT.md)
7. [Entrega F1 — tabela vigente no WhatsApp](40_delivery/F1_PRICE_LIST_GATEWAY.md)
8. [Backlog da interface administrativa](40_delivery/ADMIN_INTERFACE_BACKLOG.md)

## Artefatos executáveis

- [OpenAPI](../openapi/crm-api.yaml)
- [Migração PostgreSQL](../db/migrations/0001_initial.sql)
