# AGENT SKILL PROJECT

## Contrato de execução

Este arquivo define o domínio, os limites e as trilhas do CRM Conversacional API.

## Limites do sistema

- O WhatsApp Gateway recebe, normaliza, roteia e envia mensagens.
- O CRM Conversacional API detém clientes, catálogo, preços, regras, ofertas, conversas e persistência.
- A LLM interpreta e redige; cálculos e transições de estado pertencem à API.
- PostgreSQL é a fonte persistente do domínio comercial.

## Invariantes

- Nenhum preço é inventado pela LLM.
- Toda oferta enviada foi aprovada por uma pessoa.
- Itens enviados são fotografias imutáveis.
- Eventos externos são idempotentes.
- Valores monetários usam representação decimal.
- Competência mensal é dado, não nome de tabela.

## Trilhas

1. Fundação executável e banco.
2. Clientes, contatos e catálogo.
3. Tabelas de preço e regras.
4. Prévia, criação, aprovação e envio de ofertas.
5. Conversas, mensagens e observabilidade.
6. Integração completa com o Gateway.
7. MCP opcional, somente após estabilização da API HTTP.

## Regra de compatibilidade

Mudanças no contrato com o Gateway devem atualizar simultaneamente `docs/30_architecture/API_CONTRACT.md`, `openapi/crm-api.yaml` e `docs/00_meta/08_decisions_log.md`.
