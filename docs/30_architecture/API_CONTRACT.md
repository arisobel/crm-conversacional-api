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

## Corte F1 — tabela vigente para o Gateway

- `GET /price-lists/current/by-whatsapp/{phone}` usa a mesma autenticação HMAC e o
  mesmo escopo de tenant da busca de contato. Ele retorna o contato ativo, uma única
  tabela `ACTIVE` vigente e seus itens ativos de catálogo.
- Valores monetários são strings decimais. Para `OUT_OF_STOCK`, `SUSPENDED` e `CONSULT`,
  `base_price` é `null`; o Gateway deve apresentar a disponibilidade, nunca `R$ 0,00`.
- O endpoint não aplica desconto, frete, imposto nem aprova uma oferta. Essas regras e a
  mensagem comercial final pertencem aos cortes posteriores e permanecem determinísticos.
- No Gateway publicado, `tabela`, `tabela de preço` e `tabela de preços` chamam esse
  endpoint. Mensagens diferentes preservam o lookup de cadastro existente.

## Próximo corte F1 — item específico

- O CRM expõe uma consulta interna assinada de itens da tabela vigente por contato
  WhatsApp e termo de busca. O termo é comparado deterministicamente com SKU, nome
  comercial, especificação e família.
- O Gateway reconhecerá `produto <termo>` e devolverá um item quando houver resultado
  inequívoco; havendo vários, apresentará opções com SKU e especificação para o contato
  refinar a consulta.
- A operação continua somente de leitura, no tenant informado pelo Gateway, e não cria
  oferta nem aplica regra comercial.

## Manifesto de capacidades por sessão

- `GET /internal/interaction-capabilities` exige o mesmo HMAC e tenant das demais
  consultas internas. Ele publica intenções, aliases, exemplos, slots e identificadores de
  ação permitida do CRM.
- O Gateway busca o manifesto na primeira mensagem da sessão `linha + fluxo + contato` e
  respeita `session_ttl_seconds`. O cache não contém tabela, preço ou texto de conversa.
- O Gateway executa somente ações locais previamente associadas aos identificadores
  publicados. O CRM não fornece URL, SQL, fórmulas ou código executável no manifesto.
- A LLM, quando usada pelo Gateway, é limitada a uma saída estruturada com `intent_id` e
  slots declarados no manifesto. A consulta de dados, cálculo e resposta comercial
  continuam determinísticos no CRM.

## Proposta de contrato para campanhas de WhatsApp

**Estado: proposta documental; não há endpoint, OpenAPI, executor ou alteração
de produção neste corte.** O objetivo é fixar as propriedades de segurança e a
direção dos dados antes de escolher o formato final.

### Fronteira e autenticação

O CRM resolve a campanha comercial e o Gateway executa o canal. Os dois sentidos
usam a mesma autenticação interna já estabelecida: `X-Tenant-Slug`,
`X-Timestamp` e `X-Signature`, com HMAC de `timestamp.method.path.body` e
rejeição de timestamp fora da janela. O corpo é serializado uma vez, assinado
nos mesmos bytes e nunca contém segredo da Meta.

O Gateway não aceita URL, executor, SQL, template bruto nem regra de autorização
trazidos pelo CRM. O CRM não aceita evento sem tenant autenticado, identificador
externo e correlação de campanha/destinatário. Uma credencial de serviço deve
ter escopo apenas da integração CRM ↔ Gateway; ela não substitui a sessão e as
permissões do usuário que originou a campanha.

### CRM → Gateway: comando operacional proposto

Proposta de um único recurso interno, a ser confirmado com o Gateway:

```
POST /internal/whatsapp-campaigns
```

Envelope conceitual:

```json
{
  "command_id": "uuid-idempotente-gerado-pelo-crm",
  "operation": "CONFIRM",
  "crm_campaign_id": "uuid",
  "gateway_campaign_id": "opcional-em-cancelamento",
  "template": {
    "id": "identificador-operacional-permitido",
    "language": "pt_BR"
  },
  "recipients": [
    {
      "crm_recipient_id": "uuid",
      "customer_id": "uuid",
      "contact_id": "uuid",
      "whatsapp_e164": "+5511999999999",
      "variables": {"nome": "Cliente"}
    }
  ]
}
```

As operações candidatas são `CONFIRM` e `CANCEL`; o vocabulário não está
fechado. O rascunho é criado e auditado no CRM, portanto não é um comando de
envio ao Gateway. `CONFIRM` só é aceito para uma campanha já confirmada no CRM.
`CANCEL` pede que o Gateway interrompa somente o que ainda estiver pendente.
Para públicos grandes, o CRM não envia um comando de confirmação sem a revisão
nominal exigida pelo produto.

`command_id` é obrigatório e único por tenant/operação; repetição precisa
devolver o mesmo resultado, inclusive após timeout. O Gateway é responsável por
validar se o template é permitido, aplicar consentimento/opt-out na prévia e
imediatamente antes da tentativa de envio, e controlar fila, taxa e limites da
Meta. Uma recusa por consentimento não é erro de transporte nem justificativa
para retry cego.

O formato final precisa decidir se a prévia de consentimento será chamada nesse
mesmo recurso (`operation=PREVIEW`) ou publicada pelo catálogo operacional do
Gateway. Em ambos os casos, o CRM não usa `customer_interactions` como fonte de
consentimento ou de janela de 24 horas.

### Gateway → CRM: eventos de projeção propostos

Proposta de endpoint separado para que o CRM forme a visão comercial sem ler o
banco do Gateway:

```
POST /internal/whatsapp-campaign-events
```

Envelope conceitual:

```json
{
  "events": [
    {
      "event_id": "identificador-imutavel-do-gateway",
      "event_type": "RECIPIENT_STATUS_CHANGED",
      "occurred_at": "2026-08-31T15:00:00Z",
      "gateway_campaign_id": "camp_123",
      "crm_campaign_id": "uuid",
      "crm_recipient_id": "uuid",
      "gateway_message_id": "wamid.HBg...",
      "status": "DELIVERED",
      "reason": null
    }
  ]
}
```

Eventos necessários incluem criação/correlação de campanha, resultado de prévia
de consentimento, alteração de estado de destinatário (`PENDING`, `SENT`,
`DELIVERED`, `READ`, `FAILED`), exclusão por consentimento, falha/cancelamento e
resposta do cliente. Resposta pode referenciar a interação projetada em
`/internal/interactions`, mas este vínculo não substitui nem duplica a ingestão
canônica da mensagem.

`event_id` é obrigatório e idempotente no CRM por tenant e origem. A entrega é
assíncrona, com retry e por-item quando em lote: evento inválido não deve apagar
nem reverter os demais. Eventos podem chegar repetidos ou fora de ordem; o CRM
guarda momento/origem e não regride um estado mais recente sem regra de
reconciliação explícita. A política de ordenação, resposta HTTP e reconciliação
periódica são pendências a fechar antes de codificar.

### Compatibilidade e capacidades conversacionais

Nenhuma capability de campanha entra no `business-capability-manifest/v1` até o
Gateway registrar a ação e seu executor. As propostas
`CRM_PREVIEW_WHATSAPP_CAMPAIGN_AUDIENCE`,
`CRM_CREATE_WHATSAPP_CAMPAIGN_DRAFT`,
`CRM_CONFIRM_WHATSAPP_CAMPAIGN`, `CRM_CANCEL_WHATSAPP_CAMPAIGN` e
`CRM_GET_WHATSAPP_CAMPAIGN_STATUS` deverão declarar `mode`, confirmação,
idempotência, slots e vocabulário segundo ADR-022 a ADR-026. A LLM limita-se a
intenção e slots; o CRM calcula audiência e o Gateway executa o envio.

Antes de publicar o contrato, os dois repositórios precisam compartilhar fixture
e testes para assinatura, replay, duplicidade, timeout, revogação de
consentimento entre prévia e envio, falha parcial, cancelamento e isolamento de
carteira/tenant.
