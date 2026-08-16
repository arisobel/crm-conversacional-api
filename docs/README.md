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
2. [Direção do produto — CRM de representantes](10_product/REPRESENTATIVE_DIRECTION.md)
3. [Progresso](00_meta/07_progress.md)
4. [Backlog](00_meta/09_backlog.md)
5. [Roadmap](10_product/MVP_ROADMAP.md)
6. [Modelo-alvo](20_domain/DOMAIN_MODEL_TARGET.md)
7. [Entrega F5 — portal do representante](40_delivery/F5_REPRESENTATIVE_PORTAL.md)
8. [Decisões](00_meta/08_decisions_log.md)
9. [Contrato do projeto](00_meta/AGENT_SKILL_PROJECT.md)
10. [Manifesto](10_product/BUSINESS_FEATURE_MANIFESTO.md)

### Referência do que já está implementado

- [Modelo de domínio atual](20_domain/DOMAIN_MODEL.md)
- [Entrega F1 — tabela vigente no WhatsApp](40_delivery/F1_PRICE_LIST_GATEWAY.md)
- [Manifesto por ator no WhatsApp](30_architecture/WHATSAPP_ACTOR_MANIFEST.md) — desenho, nada implementado
- [Backlog da interface administrativa](40_delivery/ADMIN_INTERFACE_BACKLOG.md)

### Congelado

- [Backlog multiempresa](10_product/MULTI_COMPANY_BACKLOG.md) — ver ADR-013

## Artefatos executáveis

- [OpenAPI](../openapi/crm-api.yaml)
- [Migração PostgreSQL](../db/migrations/0001_initial.sql)
