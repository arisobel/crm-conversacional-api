# Contrato da API

A fonte executável do contrato é `openapi/crm-api.yaml`.

## Limite Gateway → CRM

O Gateway envia eventos canônicos para `POST /internal/whatsapp/events`, assinados, datados e identificados por chave idempotente.

## Operações do MVP

- localizar cliente por WhatsApp;
- listar produtos preferenciais;
- consultar tabela vigente;
- calcular prévia;
- criar, consultar e aprovar oferta;
- solicitar envio de oferta aprovada;
- registrar status de saída.

## Regras contratuais

- Dinheiro trafega como string decimal.
- Telefone usa E.164.
- IDs internos usam UUID.
- Erros usam `application/problem+json`.
- Mudança de contrato exige atualização do OpenAPI e do registro de decisões.
