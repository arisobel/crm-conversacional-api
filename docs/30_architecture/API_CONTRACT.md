# Contrato da API

A fonte executável do contrato é `openapi/crm-api.yaml`.

## Limite Gateway → CRM

O Gateway envia eventos canônicos para `POST /internal/whatsapp/events`, assinados, datados e identificados por chave idempotente.

Para consultas síncronas do primeiro corte, o Gateway resolve previamente a rota
`linha Meta → aplicativo → fluxo` no seu plano de controle e chama o CRM com
`X-Tenant-Slug`, `X-Timestamp` e `X-Signature`. A assinatura é HMAC-SHA256 do
valor UTF-8 `timestamp.method.path.body`, separado por ponto; para um `GET`, o
corpo é vazio. O CRM aceita somente o slug de tenant configurado na própria
implantação. Assim, um telefone nunca é pesquisado globalmente entre tenants.
Durante a rotação, a implantação pode aceitar temporariamente
`CRM_INTERNAL_HMAC_PREVIOUS_SECRET`, sem alterar o cabeçalho ou interromper o Gateway.

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

## Corte F0

- `GET /health` verifica apenas o processo.
- `GET /ready` verifica a conectividade com PostgreSQL e não expõe DSN ou credenciais.
- `GET /customers/by-whatsapp/{phone}` exige a autenticação interna acima, normaliza
  somente espaço, ponto, hífen e parênteses de apresentação, e retorna apenas contato,
  cliente e tenant ativos.
