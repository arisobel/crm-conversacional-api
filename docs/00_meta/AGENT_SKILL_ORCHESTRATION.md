# AGENT SKILL ORCHESTRATION

## Papel

Este arquivo controla como o trabalho do CRM Conversacional API é lido, executado, registrado e retomado sem fragmentar a verdade.

## Fontes únicas

| Função | Arquivo |
|---|---|
| Progresso | `docs/00_meta/07_progress.md` |
| Decisões | `docs/00_meta/08_decisions_log.md` |
| Backlog | `docs/00_meta/09_backlog.md` |
| Problemas conhecidos | `docs/00_meta/KNOWN_ISSUES.md` |
| Contrato do projeto | `docs/00_meta/AGENT_SKILL_PROJECT.md` |
| Manifesto | `docs/10_product/BUSINESS_FEATURE_MANIFESTO.md` |
| Roadmap | `docs/10_product/MVP_ROADMAP.md` |
| Regras | `docs/20_domain/BUSINESS_RULES.md` |
| Contrato da API | `docs/30_architecture/API_CONTRACT.md` |

Não criar fontes concorrentes para progresso, decisões, backlog, roadmap ou issues.

## Loop obrigatório

### Antes

1. Ler progresso, backlog, manifesto e roadmap.
2. Ler o contrato do projeto.
3. Ler o blueprint da fase ativa em `docs/40_delivery/`.
4. Consultar regras, arquitetura e contrato afetados.

### Durante

1. Preservar invariantes de negócio.
2. Atualizar OpenAPI quando a interface mudar.
3. Registrar tradeoffs em decisões.
4. Registrar somente problemas observados em `KNOWN_ISSUES.md`.

### Depois

1. Atualizar progresso.
2. Atualizar backlog.
3. Registrar decisão quando houver tradeoff.
4. Acrescentar evidência de validação.

## Prioridade atual

F0 — transformar DDL e OpenAPI em serviço executável, mantendo a separação:

`Meta Cloud API → WhatsApp Gateway → CRM API → PostgreSQL`

A LLM opera por funções controladas da API e não possui autoridade sobre preço, regras, SQL ou envio sem aprovação.

## Antipadrões

- Duplicar fontes de verdade.
- Implementar sem atualizar progresso e backlog.
- Criar tabelas físicas por `YYYYMM`.
- Permitir cálculo comercial não determinístico.
- Alterar oferta histórica após envio.
- Misturar responsabilidades do Gateway com domínio comercial.
- Tratar MCP como requisito antes de estabilizar a API HTTP.
