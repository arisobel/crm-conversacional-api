# F7 — Conversação híbrida Representante ↔ Cliente

Blueprint de entrega futura para a conversa contínua entre Cliente, Representante, Gateway, CRM-api e IA/LLM. Baseia-se na [arquitetura conceitual de Coexistence](../30_architecture/WHATSAPP_REPRESENTATIVE_COEXISTENCE.md) e não declara WhatsApp Coexistence, F7 ou automação como implementados.

## Natureza e fronteira da fase

F7 começa quando o problema deixa de ser campanha e passa a ser atendimento contínuo.

| Frente | Responsabilidade |
|---|---|
| **F6** | campanha → sender → envio → status → resposta correlacionada |
| **F7** | quem atende, quando transferir ou reassumir, o que o cliente pode consultar, autoria e reconstrução da conversa |

F7 não redefine o motor comercial de campanhas. É planejada prioritariamente para o Plano A — identidade WhatsApp do representante via Coexistence. O Plano B poderá reutilizar autoria, estado, handoff, capabilities e timeline, mas tem transporte diferente e não domina este blueprint.

## Pré-condições para implementação

O planejamento documental de F7 pode avançar; a implementação efetiva de cada fase dependente não começa sem:

1. PoC Coexistence com evidência suficiente para o Plano A;
2. F6.4 com contrato CRM ↔ Gateway funcional;
3. sender do representante resolvido de forma confiável;
4. Gateway recebendo eventos suficientes da conversa;
5. correlação Cliente ↔ Representante ↔ Linha comprovada;
6. autoria manual detectável;
7. política básica customer-facing aprovada.

Se uma pré-condição não estiver pronta, a fase dependente não começa. O gate está em [F6.4](F6_WHATSAPP_CAMPAIGNS.md#gate-técnico--whatsapp-coexistence) e na [arquitetura conceitual](../30_architecture/WHATSAPP_REPRESENTATIVE_COEXISTENCE.md#14-decisões-que-o-poc-precisa-comprovar).

## Sequência de entrega

```text
PoC Coexistence + F6.4
          |
          v
        F7.0  Decisões e contrato conceitual
          |
          v
        F7.1  Observação e autoria
          |
          v
        F7.2  Contexto e estado
          |
          v
        F7.3  Prioridade humana
          |
          v
        F7.4  Capabilities externas
          |
          v
        F7.5  BOT_ACTIVE controlado
          |
          v
        F7.6  Handoff por política
          |
          v
        F7.7  Reassunção
          |
          v
        F7.8  Timeline e supervisão
          |
          v
        F7.9  Mídias
```

A ordem privilegia observabilidade, autoria, estado e segurança antes de automação. Não é permitido tentar entregar Coexistence, estado, bot, handoff, IA e timeline no mesmo deploy.

## F7.0 — Fechamento de decisões e contrato conceitual

**Depende de:** evidências do PoC e resultado de F6.4 disponíveis para análise.

**Entrega:** decisões suficientes para implementar F7.1 sem inventar regras em código: identificador canônico da conversa; autoridade final sobre `mode`; autoria conceitual e contrato de eventos Gateway → CRM; timeout, horários e ativação automática; retenção LGPD; mídia; capabilities customer-facing; e corrida Humano × Bot.

**Critério de saída:** cada decisão necessária ao primeiro corte está registrada na fonte canônica adequada, com responsável e limite claro.

**Não inclui:** tabela, migration, payload definitivo, endpoint ou implementação de eventos.

## F7.1 — Observação e autoria da conversa

**Depende de:** F7.0, PoC aprovado para os eventos necessários e F6.4 funcional.

**Entrega:** observação e projeção futura de mensagens com autoria explícita:

```text
CUSTOMER
HUMAN
BOT
SYSTEM
BOT_HANDOFF
```

O primeiro corte cobre inbound do cliente, outbound manual do representante e outbound automático quando este vier a existir, sempre vinculados a tenant, representante, cliente, contato e linha. `smb_message_echoes` é o candidato central para autoria `HUMAN`, condicionado ao PoC; este blueprint não define seu payload.

**Critério de saída:** o CRM consegue distinguir quem produziu cada mensagem e qual conversa conceitual ela integra, sem resposta automática.

**Não inclui:** transição de modo, handoff ou execução da IA.

## F7.2 — Contexto e estado da conversa

**Depende de:** F7.1 e decisões de F7.0 sobre identidade, estado e auditoria.

**Entrega:** materialização futura do conceito `RepresentativeConversationContext`, com identificação correta da conversa, timestamps relevantes, leitura de estado e transições auditáveis. Os estados candidatos são:

```text
HUMAN_ACTIVE
BOT_ACTIVE
WAITING_HUMAN
BOT_ASSIST
```

**Critério de saída:** cada conversa possui modo explícito, consultável e auditável, sem cruzamento entre clientes, representantes ou tenants.

**Não inclui:** escolha de schema, automação de resposta ou reassunção.

## F7.3 — Prioridade humana e handoff imediato

**Depende de:** F7.1, F7.2 e evidência de autoria manual do PoC.

**Entrega:** a invariante de que mensagem manual do representante prevalece sobre automação.

```text
BOT_ACTIVE
    |
mensagem manual
    |
Gateway detecta
    |
    v
HUMAN_ACTIVE
```

O corte deve cobrir supressão ou cancelamento de resposta pendente, corridas, idempotência, eventos duplicados e echo atrasado.

**Critério de saída:** o humano assume sem competir com o bot; nenhuma resposta automática é enviada depois de intervenção humana detectada a tempo.

**Não inclui:** decisão de negócio para reassunção automática.

## F7.4 — Capabilities customer-facing

**Depende de:** F7.0, F7.2 e fronteira de autorização aprovada.

**Entrega:** primeiro conjunto pequeno de capabilities externas, limitado ao cliente e ao contexto da conversa. Exemplos conceituais:

```text
CUSTOMER_GET_PRODUCT_INFO
CUSTOMER_GET_CURRENT_PRICE
CUSTOMER_GET_AVAILABLE_PRICE_LIST
CUSTOMER_GET_DOCUMENT
CUSTOMER_REQUEST_REPRESENTATIVE
```

Capacidades explicitamente proibidas nesse contexto:

```text
LIST_REPRESENTATIVE_CUSTOMERS
GET_OTHER_CUSTOMER_HISTORY
GET_INTERNAL_MARGIN
GET_OTHER_CUSTOMER_PRICES
```

**Critério de saída:** uma pergunta externa acessa somente dados permitidos do cliente e da conversa atual.

**Não inclui:** adicionar capabilities ao manifesto real antes de contrato, allowlist, executor e testes correspondentes.

## F7.5 — `BOT_ACTIVE` controlado

**Depende de:** F7.3, F7.4, F6.4 e sender do representante validado.

**Entrega:** resposta automática controlada ao cliente pela linha do representante:

```text
Cliente → Gateway → interpretação → capability autorizada → CRM-api
        → resultado estruturado → LLM → Gateway → Cliente
```

Regras obrigatórias: LLM não acessa banco; CRM-api autoriza; Gateway controla o canal; o sender permanece do representante; a resposta obedece à política e à janela Meta aplicável; capability interna não é reutilizada implicitamente.

**Critério de saída:** o bot responde com dado autorizado sem ultrapassar a alçada do cliente, do representante ou do tenant.

**Não inclui:** negociação autônoma, exceção comercial ou reassunção automática.

## F7.6 — Handoff por política

**Depende de:** F7.5 e política validada de classificação e escalonamento.

**Entrega:** tratamento determinístico para pedidos que exigem humano, como desconto, negociação excepcional, reclamação, alteração financeira ou condição fora de regra.

```text
LLM: intent = NEGOTIATE_DISCOUNT
        |
        v
Política: requires_human = true
        |
        v
mode = WAITING_HUMAN
```

**Critério de saída:** pedidos definidos como humanos nunca são resolvidos livremente pela IA.

**Não inclui:** LLM como autoridade de política ou qualquer atalho de desconto.

## F7.7 — Reassunção automática

**Depende de:** F7.6 e políticas explícitas aprovadas.

**Entrega:** retorno controlado de `HUMAN_ACTIVE` para `BOT_ACTIVE`, somente por política válida: timeout, fora do horário, ativação explícita do representante ou tipo de conversa.

**Critério de saída:** o bot reassume apenas a conversa correta, de forma configurável e auditável.

**Não inclui:** valores padrão de timeout ou horário definidos por suposição.

## F7.8 — Timeline e supervisão

**Depende de:** F7.1 a F7.7 para os eventos que cada uma introduzir.

**Entrega:** projeção gerencial no CRM capaz de reconstruir:

```text
campanha API → cliente → representante → bot → handoff → representante
```

Ela preserva autoria, timestamps, vínculo de campanha quando existente, contexto, eventos de handoff, modo vigente e histórico gerencial. O acesso segue escopo: `REPRESENTATIVE` vê sua carteira; `MANAGER`/`ADMIN`, somente a alçada do tenant.

**Critério de saída:** supervisão identifica quem falou, quando, em qual contexto e por que houve troca de atendimento.

**Não inclui:** tornar o CRM autoridade dos eventos do canal.

## F7.9 — Mídias e evolução

**Depende de:** estabilidade das fases anteriores e política de retenção aprovada.

**Entrega:** evolução posterior, incremental, para imagem, PDF, áudio, vídeo se suportado e necessário, documentos e mensagens interativas.

**Critério de saída:** mídia desconhecida falha de modo controlado e a mídia suportada preserva autorização, autoria e retenção adequadas.

**Não inclui:** bloquear o primeiro corte de F7; texto é a prioridade inicial.

## Estratégia de entrega e primeira entrega recomendada

O primeiro marco de F7 é **observabilidade segura**, não IA respondendo:

> Gateway observa mensagens do cliente e mensagens manuais do representante; CRM projeta autoria correta e contexto da conversa; nenhuma automação responde.

Essa entrega corresponde a F7.1, apoiada nas decisões de F7.0 e na identificação conceitual da conversa necessária para a projeção. O estado com transições e toda a automação permanecem nas fases seguintes.

## Testes conceituais obrigatórios

As implementações futuras devem cobrir, no mínimo:

- cliente A não cruza conversa com cliente B;
- representante A não opera linha de representante B;
- tenant A não vê tenant B;
- mensagem manual muda para `HUMAN_ACTIVE`;
- evento manual duplicado não cria transição duplicada;
- bot não responde após handoff;
- resposta automática é idempotente;
- cliente não consulta dado de terceiro nem margem interna;
- LLM não inventa capability inexistente;
- timeout não reassume conversa errada;
- mudança de carteira não reescreve histórico;
- evento fora de ordem não corrompe autoria;
- mídia desconhecida falha de modo controlado;
- indisponibilidade do Gateway não cria estado falso no CRM.

## Segurança, autoridades e LLM

F7 preserva tenant, carteira e customer scope obrigatórios, allowlist de capabilities, HMAC entre serviços, idempotência e auditoria. Texto do cliente não define identidade e prompt injection nunca amplia capabilities.

| Componente | Autoridade |
|---|---|
| Gateway | eventos do canal, sender, webhook, `wamid`, linha, envio, estado operacional imediato, detecção de mensagem manual e bloqueio imediato do bot |
| CRM-api | representante, cliente, carteira, dados, permissões, capability, política comercial e projeção histórica |
| LLM | classificar, extrair slots e redigir somente a partir de resultado autorizado |

A LLM não escolhe cliente, linha ou tenant; não concede capability, não acessa SQL ou credenciais, não ignora handoff e não decide política comercial ou desconto fora de capability.

## Questões deliberadamente abertas

- persistência, lock/race e cancelamento de geração em andamento;
- timeout, horários, SLA e disponibilidade do representante;
- interface de automação e primeiro pacote de capabilities;
- retenção LGPD, mídia e custo/limite de automação;
- fallback quando CRM-api ou Gateway estiver indisponível;
- contrato físico de eventos e mecanismo de estado.

Essas questões não devem ser respondidas por suposição. Plano B pode reutilizar os conceitos deste blueprint, mas, se necessário, terá blueprint complementar para seu relay/transporte.

## Definição de pronto de F7

Conceitualmente, F7 estará pronta quando uma conversa entre cliente e representante puder alternar de forma segura e auditável entre humano e automação, preservando sender correto, autoria, escopo de cliente, capabilities autorizadas, handoff determinístico e timeline no CRM — sem que a LLM controle identidade, destinatário ou alçada.
