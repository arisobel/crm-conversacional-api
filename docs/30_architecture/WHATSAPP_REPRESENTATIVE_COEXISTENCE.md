# WhatsApp Coexistence e conversa híbrida do representante

**Natureza:** arquitetura-alvo conceitual do Plano A.  
**Estado:** não declara WhatsApp Coexistence como implementado e não substitui o PoC técnico no Gateway.  
**Escopo:** identidade WhatsApp do representante, conversa direta com o cliente, observação do canal, automação eventual e seus limites de autorização.

## 1. Propósito

Este arquivo define a arquitetura-alvo conceitual do Plano A: campanhas e atendimento podem usar a identidade WhatsApp Business do próprio representante, desde que WhatsApp Coexistence seja comprovado na prática. O objetivo é preservar a relação direta Representante ↔ Cliente, enquanto o Gateway observa o canal e, quando uma política permitir, pode operar automação limitada.

Ele não é contrato físico, não define persistência, endpoint, payload de webhook ou schema. A fonte de contexto da direção é a [Fonte — Plano A / Plano B WhatsApp](../90_references/CRM_TEXTIL_FONTE_PLANO_A_B_WHATSAPP.md).

## 2. Escopo e não escopo

Este documento estabelece conceitos, responsabilidades, invariantes e perguntas que o PoC deve responder. Ficam fora do escopo a implementação de Coexistence, Embedded Signup ou handlers de webhook; tabelas, migrations, ORM, endpoints, services ou flags; contrato definitivo Gateway ↔ CRM-api; máquina de transição física; capabilities reais; e desenho detalhado do relay do Plano B.

## 3. Relação com Plano A, Plano B, F6 e F7

O [Plano A](../10_product/WHATSAPP_CAMPAIGNS.md#plano-a--identidade-do-representante) é a direção preferencial: o Gateway envia pela identidade WhatsApp Business vinculada ao representante após o CRM-api determinar e congelar a campanha. O cliente vê o número do representante e a continuidade humana pode permanecer no mesmo chat.

O Plano B permanece fallback. Caso o PoC do Plano A resulte em NO-GO, ou haja necessidade complementar, o Gateway poderá usar linha WABA central e correlação por Reply/contexto técnico. A LLM nunca escolhe o destinatário de uma resposta humana nesse modelo.

F6 continua responsável pelo ciclo de campanha: campanha, envio pelo Gateway, status e resposta correlacionada. A futura F7 começa quando a questão passa a ser quem conduz a conversa, como ocorre handoff e quais dados o cliente pode consultar. A conversa híbrida não amplia F6.

## 4. Fundamentos já existentes e limite da evidência

O Gateway já possui roteamento por `phone_number_id` para `whatsapp_lines`, integrações Meta separadas em `meta_whatsapp_integrations`, campanhas vinculadas a linha e integração, e correlação de campanhas por `wamid` e `context.wamid`.

Esses fundamentos não comprovam Coexistence. Em especial, não há tratamento estabelecido para eventos específicos de Coexistence, como `smb_message_echoes`. O PoC precisa validar o comportamento real da Meta e do WhatsApp Business App antes de qualquer implementação definitiva.

## 5. Conceitos de identidade

A identidade comercial do representante e a identidade técnica do canal são relacionadas, mas distintas:

```text
Representante / usuário
        !=
Identidade técnica WhatsApp de envio
```

O CRM-api identifica o representante, a carteira e a autorização comercial. O Gateway resolve linha WhatsApp autorizada, integração Meta e sender. Segredos, `phone_number_id`, WABA e credenciais permanecem fora da autoridade do CRM-api.

### Actor × channel owner × counterparty

O conceito já existente de `actor`, definido em [WHATSAPP_ACTOR_MANIFEST.md](WHATSAPP_ACTOR_MANIFEST.md), é preservado:

```text
actor
    = pessoa que está acionando uma capability

channel_owner
    = representante cuja identidade WhatsApp está sendo utilizada

counterparty
    = pessoa externa do outro lado da conversa
```

| Situação | `actor` | `channel_owner` | `counterparty` |
|---|---|---|---|
| Carlos envia comando ao robô central | Carlos, `REPRESENTATIVE` | não aplicável | não aplicável |
| João escreve para o WhatsApp de Carlos | João, se acionar capability externa | Carlos | João |
| Bot responde pela linha de Carlos | o bot não herda papel humano | Carlos | João |

Na conversa direta, João não vira representante nem recebe alçada interna de Carlos. O uso da linha de Carlos determina em nome de quem o canal fala; a identidade de João determina o que pode ser revelado.

## 6. Contexto conceitual da conversa

Cada conversa representante ↔ cliente exige contexto adicional ao `actor`:

```text
RepresentativeConversationContext

tenant
representative_user_id
customer_id
contact_id
gateway_line_id
phone_number_id
mode
last_customer_message_at
last_human_message_at
last_bot_message_at
```

Esse é um modelo conceitual. Não especifica tabela, coluna, ORM, endpoint ou formato de evento. O vínculo identifica uma conversa no contexto de representante + cliente + linha WhatsApp, e não somente por telefone.

## 7. Autoridades operacionais e comerciais

### Gateway

O Gateway é a autoridade operacional sobre:

- linha e sender;
- direção da mensagem, webhook e `wamid`;
- mensagens enviadas e recebidas;
- eventos de Coexistence;
- modo operacional vigente da conversa;
- decisão imediata de permitir, bloquear, cancelar ou suprimir envio automático.

Ele é o único componente que pode observar a Cloud API e os eventos originados no WhatsApp Business App. Por isso, não deve depender de consulta ao CRM-api para descobrir se o representante acabou de enviar uma mensagem manual.

### CRM-api

O CRM-api é a autoridade sobre:

- representante, carteira, cliente e contato;
- permissões, regras comerciais e dados estruturados;
- capabilities autorizadas;
- informação que pode ser exposta ao interlocutor externo;
- projeção comercial e histórica da conversa.

O CRM-api pode receber projeções do contexto e dos eventos, mas não substitui a autoridade do Gateway sobre o estado operacional instantâneo do canal.

## 8. Estados conceituais Humano ↔ IA

Os estados abaixo são candidatos arquiteturais. A persistência física e a máquina de transição definitiva só serão fechadas após o PoC e no escopo de F7.

| Estado | Significado |
|---|---|
| `HUMAN_ACTIVE` | O representante conduz a conversa; automação observa e registra, mas não responde automaticamente. |
| `BOT_ACTIVE` | O Gateway pode acionar capabilities autorizadas e enviar resposta automática. |
| `WAITING_HUMAN` | A automação interrompeu a resposta e aguarda intervenção do representante. |
| `BOT_ASSIST` | A IA auxilia internamente, mas não envia mensagem ao cliente. |

## 9. Prioridade humana e handoff

Invariante central:

> **Uma mensagem manual do representante sempre prevalece sobre a automação.**

```text
BOT_ACTIVE
    |
representante envia mensagem pelo WhatsApp Business App
    |
Gateway observa evento de echo
    |
    v
HUMAN_ACTIVE
```

Se houver resposta automática pendente, ela deve ser cancelada, suprimida ou impedida de enviar quando a intervenção humana for detectada a tempo. O mecanismo exato, inclusive conflitos e corridas, permanece aberto nesta etapa.

### `smb_message_echoes` no PoC

`smb_message_echoes` é um evento técnico esperado do PoC para identificar mensagem enviada manualmente pelo representante no WhatsApp Business App. Não há payload definitivo nem handler definido por este documento.

O PoC deverá provar:

1. recebimento do evento;
2. identificação da linha;
3. identificação do interlocutor externo;
4. correlação com a conversa correta;
5. projeção da autoria como `HUMAN`.

## 10. Reassunção automática pelo bot

Uma política explícita e auditável pode permitir que a automação reassuma uma conversa. As possibilidades conceituais são:

- **Inatividade:** `HUMAN_ACTIVE` pode passar para `BOT_ACTIVE` após timeout configurável.
- **Horário:** fora do horário de atendimento humano, a automação pode ser permitida conforme política.
- **Comando explícito:** futuramente, o representante pode autorizar algo como “Assuma minhas conversas até amanhã às 8h”.
- **Natureza da solicitação:** perguntas simples e autorizadas podem permanecer automáticas; assunto sensível, negociação, exceção comercial ou risco exige handoff.

A LLM pode classificar intenção ou risco, mas não controla o handoff sozinha:

```text
LLM: intenção = pedir desconto
        |
        v
Política validada: requires_human = true
        |
        v
conversation.mode = WAITING_HUMAN
```

Nunca é aceitável que a LLM decida livremente se fala ou não em nome do representante.

## 11. Capabilities customer-facing e autorização

Responder pela linha do representante não concede ao cliente as permissões internas dele. Carlos pode consultar carteira, histórico de outros clientes, margem e dados comerciais internos; João não pode receber esses dados por estar conversando com a linha de Carlos.

O conjunto conceitual `CUSTOMER_FACING_CAPABILITIES` representa capacidades restritas ao interlocutor externo. Exemplos possíveis:

```text
CUSTOMER_GET_CURRENT_PRICE
CUSTOMER_GET_PRODUCT_INFO
CUSTOMER_GET_AVAILABLE_PRICE_LIST
CUSTOMER_GET_OWN_ORDER_STATUS
CUSTOMER_GET_DOCUMENT
CUSTOMER_REQUEST_REPRESENTATIVE
```

Exemplos que não podem ser expostos nesse contexto:

```text
LIST_REPRESENTATIVE_CUSTOMERS
GET_OTHER_CUSTOMER_HISTORY
GET_INTERNAL_MARGIN
GET_OTHER_CUSTOMER_PRICES
```

Esses nomes não são capabilities reais nem alteram o manifesto atual. Servem somente para estabelecer a fronteira: identidade do canal e identidade do interlocutor são dimensões de autorização independentes.

## 12. Regra de execução da LLM

```text
Cliente
   |
   v
Gateway
   |
   v
interpretação
   |
   v
capability autorizada
   |
   v
CRM-api
   |
   | autorização
   | regra de negócio
   | escopo do cliente
   v
resultado estruturado
   |
   v
LLM
   |
   | redação
   v
Gateway
   |
   v
Cliente
```

> A LLM interpreta e redige. O CRM-api autoriza e fornece dados. O Gateway controla o canal.

A LLM não recebe acesso direto ao PostgreSQL, credenciais Meta ou poder de escolher destinatário de mensagem humana.

## 13. Autoria e timeline

Toda mensagem precisa manter autoria conceitual explícita:

```text
CUSTOMER
HUMAN
BOT
SYSTEM
BOT_HANDOFF
```

Exemplo de timeline futura:

```text
09:15 HUMAN       campanha ou resposta manual do representante
09:22 CUSTOMER    pergunta do cliente
09:27 BOT         resposta autorizada
09:29 BOT_HANDOFF automação aguarda humano
09:31 HUMAN       representante reassume
```

O CRM-api deve futuramente conseguir projetar uma timeline única: campanha API, resposta do cliente, mensagem manual do representante, resposta do bot, handoff e reassunção humana. O Gateway continua sendo autoridade dos eventos do canal; o CRM mantém a projeção comercial e histórica.

## 14. Decisões que o PoC precisa comprovar

Sem reproduzir o roteiro P0–P12, o PoC descrito na [fonte de projeto](../90_references/CRM_TEXTIL_FONTE_PLANO_A_B_WHATSAPP.md) deve comprovar pelo menos:

- a mesma linha funcionando no WhatsApp Business App e na Cloud API;
- mensagem enviada por API aparecendo no aplicativo do representante;
- inbound do cliente chegando ao Gateway;
- outbound manual gerando echo observável;
- echo com correlação suficiente para a conversa;
- preservação do sender correto;
- possibilidade de alternância humano/bot na mesma conversa;
- reconstrução de timeline coerente.

Um resultado negativo não invalida o motor comercial de campanhas: orienta o uso do Plano B como fallback, sem criar um segundo motor no CRM-api.

## 15. Questões deliberadamente abertas

- persistência física do `RepresentativeConversationContext`;
- timeout padrão e políticas de horário;
- política por representante para automação;
- cancelamento de resposta em voo;
- conflito entre echo humano e resposta automática;
- primeiro conjunto de capabilities customer-facing;
- retenção LGPD da conversa híbrida;
- interface de ativação/desativação do modo automático;
- contrato exato Gateway ↔ CRM-api para eventos;
- formato definitivo de autoria;
- política para mensagens multimídia.

## 16. Invariantes

1. O CRM-api não chama a Meta diretamente.
2. O Gateway não decide regra comercial.
3. A LLM não acessa o banco diretamente.
4. A LLM não escolhe destinatário de resposta humana.
5. Humano prevalece sobre automação.
6. Cliente não herda permissões do representante.
7. Identidade do canal é diferente da identidade do interlocutor.
8. Toda mensagem preserva autoria.
9. O estado da conversa deve ser auditável.
10. Plano A depende de PoC antes de implementação definitiva.
11. Plano B permanece fallback.
12. F6 e F7 permanecem escopos separados.
