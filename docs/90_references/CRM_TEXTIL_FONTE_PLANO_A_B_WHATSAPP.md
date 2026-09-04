# CRM-Têxtil / Gateway — Fonte de Projeto
## Comunicação Representante ↔ Cliente via WhatsApp

**Status:** fonte de decisão e roteiro técnico  
**Data de consolidação:** 2026-09-03  
**Repositórios de referência:**
- `arisobel/crm-conversacional-api` — **CRM-api**
- `arisobel/whatsapp-webhook-caprover` — **Gateway**

---

## 1. Contexto

Após reunião com o cliente principal do CRM-Têxtil, o fluxo desejado para comunicação entre **Representante e Cliente** foi refinado em duas alternativas:

- **Plano A — preferencial:** o robô/WABA recebe o comando do representante, mas o disparo efetivo aos clientes sai do **próprio número WhatsApp Business do representante**. A conversa posterior ocorre diretamente entre representante e cliente.
- **Plano B — alternativo/fallback:** o disparo sai da linha WABA central. As respostas dos clientes são retransmitidas ao representante e as respostas humanas do representante são encaminhadas ao cliente pelo Gateway.

A decisão atual é **investigar e priorizar o Plano A**, mantendo o Plano B documentado como alternativa.

---

## 2. Premissa central de arquitetura

Independentemente do Plano A ou B, não devem existir dois motores comerciais de campanha.

O desenho deve preservar:

### CRM-api
Fonte de verdade para:
- representante;
- carteira;
- cliente;
- contatos;
- grupos e segmentações;
- critérios comerciais;
- audiência;
- permissões;
- auditoria;
- projeção/histórico comercial da campanha.

### Gateway
Fonte de verdade para:
- canal WhatsApp / Meta Cloud API;
- linhas WhatsApp;
- credenciais;
- templates operacionais;
- consentimento/opt-out;
- envio efetivo;
- webhooks;
- estados técnicos;
- correlação de mensagens.

### Meta
Responsável por:
- WhatsApp Business Platform;
- WABA;
- `phone_number_id`;
- aprovação de templates;
- regras de marketing;
- janela de atendimento;
- qualidade e limites do canal.

---

# 3. Plano A — Arquitetura preferencial

## 3.1 Fluxo desejado

Exemplo de comando:

> “Enviar para meus clientes Grandes de Poliéster a última tabela.”

Fluxo:

```text
Representante
    |
    | comando em linguagem natural
    v
Linha WABA / Robô
    |
    v
Gateway
    |
    v
CRM-api
    |
    | identifica ator
    | aplica carteira
    | resolve audiência
    | seleciona clientes
    v
Campanha confirmada
    |
    v
Gateway / Meta Cloud API
    |
    | sender = linha WhatsApp Business
    |          do próprio representante
    v
Clientes
```

Após o disparo:

```text
Representante <---- WhatsApp direto ----> Cliente
```

O robô deixa de ser intermediário obrigatório da conversa.

---

## 3.2 WhatsApp Coexistence

A investigação técnica concluiu que o núcleo do Plano A é compatível com **WhatsApp Coexistence**.

O número do representante pode permanecer ativo no:

- **WhatsApp Business App**, utilizado normalmente no celular;

e simultaneamente estar conectado à:

- **WhatsApp Cloud API**.

Assim, o mesmo número pode:

1. receber uma campanha enviada programaticamente pela API;
2. mostrar essa mensagem no aplicativo do representante;
3. receber normalmente a resposta do cliente;
4. permitir que o representante continue a conversa manualmente pelo WhatsApp Business App.

Essa propriedade é essencial para o Plano A.

---

## 3.3 CRM como plataforma secundária

O WhatsApp permanece a principal interface operacional do representante.

O CRM funciona como plataforma complementar para:

- histórico;
- campanhas;
- segmentação;
- acompanhamento;
- supervisão;
- indicadores;
- auditoria;
- gestão da carteira;
- registro das interações.

O objetivo é evitar que o representante precise operar uma “caixa de entrada de CRM” para continuar conversas que naturalmente pertencem ao WhatsApp.

---

## 3.4 Espelhamento das mensagens manuais

No modo Coexistence, mensagens enviadas manualmente pelo representante no WhatsApp Business App podem gerar eventos de webhook, incluindo eventos do tipo:

`Smb_message_echoes`

Isso abre caminho para:

```text
Representante responde manualmente
        |
        v
WhatsApp Business App
        |
        v
Meta
        |
        v
Gateway
        |
        v
CRM-api
        |
        v
Timeline / Histórico do Cliente
```

Portanto, é tecnicamente possível manter o CRM atualizado sem obrigar o representante a abandonar o WhatsApp.

---

# 4. Plano B — Arquitetura alternativa

Caso o Plano A encontre impedimento operacional, regulatório ou de onboarding, o Plano B permanece como fallback.

## 4.1 Fluxo

```text
Representante
    |
    v
WABA / Gateway
    |
    v
Cliente
```

Resposta:

```text
Cliente
    |
    v
WABA / Gateway
    |
    v
Representante
```

Exemplo de retransmissão:

> `[Cliente: João Silva] Sim, manda-me a tabela. Tenho interesse especial no Elastano 20.`

---

## 4.2 Regra determinística de Reply

Decisão funcional:

> **Reply nativo sobre uma mensagem-relay de cliente = resposta destinada àquele cliente.**

> **Mensagem sem Reply = novo comando ou nova interação com o robô.**

O roteamento de respostas humanas **não deve ser decidido pela LLM**.

A referência usada deve ser técnica:

```text
context.wamid
    |
    v
relay_message
    |
    v
campaign_recipient_id
    |
    v
customer_id / contact_id
```

O prefixo `[Cliente: João Silva]` é apenas UX.

---

## 4.3 Múltiplas conversas simultâneas

Não deve existir estado do tipo:

```text
active_customer = João
```

Cada Reply identifica seu próprio destinatário.

Isso permite que o representante tenha várias conversas simultâneas sem risco de uma resposta ser enviada ao cliente errado.

---

## 4.4 Mídias

O Plano B deve prever evolução para:

1. texto;
2. imagem;
3. PDF/documentos;
4. áudio;
5. demais mídias suportadas.

A recomendação é validar primeiro texto bidirecional e só depois ampliar.

---

# 5. Relação entre Plano A e Plano B

Os dois planos compartilham toda a inteligência comercial anterior ao envio:

```text
Comando do representante
        |
        v
Gateway
        |
        v
CRM-api
        |
        +-- identidade
        +-- carteira
        +-- critérios
        +-- audiência
        +-- template
        +-- confirmação
        |
        v
Campanha congelada
        |
        +----------------------+
        |                      |
        v                      v
     Plano A                Plano B
linha do representante      linha WABA central
```

Portanto:

> **Um único motor comercial no CRM-api, com estratégias de canal distintas no Gateway.**

---

# 6. Estado atual favorável dos repositórios

## Gateway

O Gateway já possui conceitos que favorecem o Plano A:

- `whatsapp_lines`;
- `phone_number_id`;
- `display_e164`;
- múltiplas linhas;
- `meta_whatsapp_integrations`;
- `waba_id`;
- credenciais Meta cifradas;
- campanhas associadas a linhas e integrações;
- Embedded Signup já presente no desenho atual.

O Gateway, portanto, não foi construído assumindo uma única linha WhatsApp.

### Lacuna atual

Ainda não há tratamento específico de eventos de Coexistence como:

- `smb_message_echoes`;
- `smb_app_state_sync`;
- sincronização/histórico Coexistence.

Essa é uma extensão futura claramente delimitada.

---

## CRM-api

O CRM já possui:

- usuários com papel `REPRESENTATIVE`;
- `users.whatsapp_e164`;
- carteira por `owner_user_id`;
- resolvedor de audiência;
- rascunhos de campanhas;
- portal de campanhas;
- escopo por representante;
- histórico/interações.

### Evolução provável

Será necessário modelar explicitamente a relação:

```text
Representative
      |
      v
WhatsApp Outbound Identity
      |
      +-- E.164
      +-- Gateway line_id
      +-- Meta phone_number_id
      +-- WABA
      +-- coexistence_status
      +-- integration_status
```

O usuário/representante e a identidade técnica de envio WhatsApp devem permanecer conceitos separados.

---

# 7. Informação nova confirmada pelo projeto

A organização responsável pelo CRM-Têxtil:

- **já está aprovada como Meta Tech Provider**;
- **já realizou serviços para terceiros dentro da plataforma Meta como Tech Provider**.

Consequência:

> O risco administrativo que inicialmente existia para implementar Embedded Signup / Coexistence próprio é significativamente menor.

A investigação deve partir da hipótese de **integração própria como Tech Provider**, e não da contratação obrigatória de um BSP/Tech Provider intermediário.

---

# 8. Templates e regras Meta

Coexistence não elimina as políticas da Meta.

O comando pode ser livre:

> “Enviar a última tabela para meus clientes grandes de poliéster.”

Mas a ação resultante continua determinística.

Para comunicações iniciadas pela empresa fora da janela permitida:

- usar template aprovado;
- respeitar consentimento;
- aplicar opt-out;
- respeitar qualidade e limites Meta.

Fluxo:

```text
Linguagem natural
Representante -> Robô
        |
        v
Intenção / slots
        |
        v
CRM resolve audiência
        |
        v
Template aprovado
        |
        v
Gateway envia pela linha do representante
```

---

# 9. Decisão de prioridade

## Plano A
**Preferencial e atualmente classificado como tecnicamente viável.**

Objetivo:

> O sistema automatiza a prospecção/campanha, mas preserva a relação humana direta entre representante e cliente.

## Plano B
**Fallback documentado.**

Deve permanecer disponível como alternativa caso o uso das linhas individuais encontre impeditivos reais.

Não deve, neste momento, ser implementado antes de esgotar a validação prática do Plano A.

---

# 10. PoC técnico do Plano A

Antes de alterar profundamente CRM-api ou Gateway, realizar um PoC com **um único número**.

## Etapa P0 — Meta / Tech Provider

Confirmar:

- app Meta que será utilizado;
- permissões atuais;
- configuração Tech Provider já existente;
- versão/configuração do Embedded Signup;
- suporte ao fluxo Coexistence no app atual;
- WABA que receberá a linha de teste.

**Situação favorável:** a organização já é Tech Provider.

---

## Etapa P1 — Número de teste

Selecionar um número:

- preferencialmente não crítico;
- migrar para WhatsApp Business App, se necessário;
- confirmar backup/histórico;
- validar funcionamento normal no aplicativo.

---

## Etapa P2 — Onboarding Coexistence

Executar Embedded Signup Coexistence.

Registrar:

- WABA ID;
- Phone Number ID;
- E.164;
- integração Meta;
- status;
- credenciais necessárias;
- webhook subscriptions.

---

## Etapa P3 — API → Business App

Enviar uma mensagem pela Cloud API utilizando o `phone_number_id` do número de teste.

Validar:

- mensagem aceita pela Meta;
- cliente recebe do número correto;
- mensagem aparece no WhatsApp Business App;
- `wamid`;
- statuses `sent`, `delivered`, `read`.

---

## Etapa P4 — Cliente → Representante

Cliente responde.

Validar:

- mensagem chega normalmente ao Business App;
- webhook recebe a mensagem;
- Gateway consegue correlacionar contato/número/linha.

---

## Etapa P5 — Representante → Cliente pelo App

Representante responde manualmente no WhatsApp Business App.

Validar:

- cliente recebe normalmente;
- Gateway recebe `smb_message_echoes`;
- payload contém informação suficiente para correlação;
- conteúdo pode ser projetado no CRM.

Essa é uma das validações mais importantes do PoC.

---

## Etapa P6 — Histórico no CRM

Sem implementar ainda o produto final, provar que é possível construir:

```text
Cliente
  |
  +-- campanha iniciada pela API
  +-- resposta do cliente
  +-- resposta manual do representante
```

em uma timeline única no CRM.

---

## Etapa P7 — Campanha mínima

Após validar P3–P6:

- selecionar 2–5 clientes de teste;
- resolver audiência no CRM;
- associar campanha ao representante;
- Gateway utilizar a linha do representante;
- enviar template aprovado;
- validar continuidade humana.

---

# 11. Critérios de aceite do PoC

O Plano A será considerado comprovado quando:

1. o mesmo número funcionar simultaneamente no WhatsApp Business App e Cloud API;
2. a API enviar usando esse número;
3. o representante visualizar o envio em seu aplicativo;
4. o cliente responder diretamente;
5. o representante responder manualmente;
6. o Gateway observar também a mensagem manual;
7. CRM conseguir relacionar as interações ao cliente e representante;
8. nenhuma etapa exigir que a conversa humana passe pelo robô;
9. o motor comercial continuar centralizado no CRM-api;
10. o Gateway continuar como único componente que fala com a Meta.

---

# 12. Princípios arquiteturais a preservar

1. **CRM não chama a Meta diretamente.**
2. **Gateway não decide carteira comercial.**
3. **LLM não escolhe destinatário de mensagem humana.**
4. **Audiência confirmada deve ser determinística e auditável.**
5. **Representante só alcança sua carteira.**
6. **Identidade comercial do representante e linha técnica WhatsApp são relacionadas, mas distintas.**
7. **Plano A e B reutilizam o mesmo motor comercial.**
8. **WhatsApp permanece a interface operacional principal do representante.**
9. **CRM é uma projeção complementar, gerencial e histórica.**
10. **Coexistence deve ser validado primeiro por PoC antes de redesenho definitivo.**

---

# 13. Próxima decisão

O próximo trabalho deve ser **executar a validação P0/P1 do PoC**, começando pela configuração Meta Tech Provider já existente e identificando exatamente:

- qual app Meta será utilizado;
- qual configuração Embedded Signup está disponível;
- como habilitar Coexistence;
- qual número será utilizado no teste;
- qual WABA receberá o número;
- quais eventos de webhook deverão ser assinados.

Somente depois desse levantamento deve ser produzido o plano de implementação definitivo nos repositórios.
---

# 14. Evolução do Plano A — Conversação híbrida Humano + IA

A investigação posterior identificou uma evolução importante do Plano A:

> **O robô pode reassumir automaticamente uma conversa direta entre Cliente e Representante, utilizando a própria identidade WhatsApp Business do representante, desde que a linha esteja em Coexistence e que as políticas de atendimento permitam a automação.**

O Plano A deixa, portanto, de ser apenas:

```text
automação da campanha
        ↓
conversa humana direta
```

e passa a admitir:

```text
automação
   ↕
humano
   ↕
IA
```

na mesma conversa e no mesmo número do representante.

## 14.1 Arquitetura conceitual

```text
                       CLIENTE
                          |
                          v
              WhatsApp do Representante
                          |
                    Coexistence
                          |
            +-------------+-------------+
            |                           |
            v                           v
     REPRESENTANTE                  GATEWAY
   WhatsApp Business                   |
        App                            v
                                   CRM-api
                                      |
                                      v
                                     LLM
```

O representante continua usando normalmente o WhatsApp Business App.

O Gateway recebe os eventos da conversa e, quando autorizado, pode responder pela Cloud API usando o mesmo `phone_number_id` da linha do representante.

Para o cliente, a conversa permanece no mesmo contato WhatsApp.

---

# 15. Reassunção automática pelo robô

Exemplo:

```text
Carlos → João
"Segue nossa tabela atualizada."

João → Carlos
"Tem Elastano 20?"

Carlos → João
"Temos sim."

João → Carlos
"E qual é o preço atual para SP?"
```

Essa última mensagem também chega ao webhook do Gateway.

O sistema pode identificar:

```text
line_id / phone_number_id = linha de Carlos
representative_user_id    = Carlos
customer_id               = João
contact_id                = contato WhatsApp de João
```

Se a política da conversa permitir automação:

```text
Gateway
   |
   v
CRM-api
   |
   | consulta capacidade autorizada
   v
Dados estruturados
   |
   v
LLM redige resposta
   |
   v
Gateway
   |
   v
Cloud API
   |
   v
João
```

A resposta continua saindo do número de Carlos.

---

# 16. Estados de atendimento da conversa

Para impedir conflito entre humano e automação, cada conversa deve possuir um estado operacional explícito.

Estados recomendados:

| Estado | Significado |
|---|---|
| `HUMAN_ACTIVE` | representante está conduzindo a conversa; robô observa e registra, mas não responde automaticamente |
| `BOT_ACTIVE` | automação pode consultar capacidades autorizadas e responder ao cliente |
| `WAITING_HUMAN` | robô interrompeu a automação e aguarda intervenção humana |
| `BOT_ASSIST` | IA auxilia o representante, mas não envia mensagem diretamente ao cliente |

O estado pertence à relação:

```text
representante + cliente + linha WhatsApp
```

e não apenas ao número do cliente.

---

# 17. Prioridade absoluta da intervenção humana

Regra arquitetural central:

> **Qualquer mensagem manual enviada pelo representante no WhatsApp Business App deve prevalecer sobre a automação.**

Quando o Gateway recebe um evento de echo da mensagem manual do representante, por exemplo via `smb_message_echoes`, a conversa deve imediatamente passar para:

```text
HUMAN_ACTIVE
```

Exemplo:

```text
conversation.mode = BOT_ACTIVE

João:
"Consegue uma condição melhor?"

Carlos envia manualmente:
"João, deixa comigo. Vou verificar uma condição especial."

Gateway recebe smb_message_echo
        |
        v
conversation.mode = HUMAN_ACTIVE
```

A IA passa a observar, mas não responde automaticamente enquanto o modo humano estiver vigente.

Essa regra deve ser determinística e não inferida por LLM.

---

# 18. Critérios possíveis para o robô reassumir

A volta para `BOT_ACTIVE` pode ocorrer por regras explícitas.

## 18.1 Inatividade do representante

Exemplo:

```text
HUMAN_ACTIVE
      |
      | representante não responde por X minutos
      v
BOT_ACTIVE
```

O valor `X` deve ser configurável por tenant, representante ou política de atendimento.

---

## 18.2 Fora do horário comercial

Exemplo:

```text
Cliente envia mensagem às 22:35
        |
        v
Representante fora do horário
        |
        v
BOT_ACTIVE
```

O robô pode responder questões permitidas e, quando necessário, informar que o representante continuará o atendimento posteriormente.

---

## 18.3 Ativação explícita pelo representante

O representante poderá, futuramente, comandar:

> “Assuma minhas conversas até amanhã às 8h.”

ou utilizar configuração no portal:

```text
Atendimento automático: ON
Até: 08:00
```

Esse recurso deve ser tratado como evolução posterior e sempre auditável.

---

## 18.4 Tipo de solicitação

Algumas solicitações podem ser classificadas como automatizáveis.

Exemplos:

```text
"Qual o preço atual do PUE 20?"
"Tem estoque?"
"Me envie a tabela atual."
"Qual a composição desse artigo?"
```

podem ser tratadas automaticamente, desde que existam capabilities autorizadas.

Solicitações como:

```text
"Preciso de 8% de desconto."
"Quero renegociar pagamento."
"Tenho uma reclamação séria."
"Quero uma condição especial."
```

podem provocar:

```text
WAITING_HUMAN
```

A classificação de intenção pode usar LLM, mas a decisão final de quais capabilities estão autorizadas deve ser determinística.

---

# 19. Janela de atendimento e mensagens livres

Quando o cliente envia uma mensagem, a conversa entra na janela de atendimento aplicável da Meta.

Dentro dessa janela, o robô pode responder pela Cloud API com mensagens permitidas sem depender de um novo template de marketing para cada resposta.

Isso favorece o fluxo:

```text
Cliente pergunta
      |
      v
Gateway
      |
      v
CRM-api
      |
      v
LLM
      |
      v
Resposta pela linha do representante
```

Fora da janela aplicável, continuam valendo as regras da Meta para mensagens iniciadas pela empresa e templates aprovados.

---

# 20. A LLM não acessa o banco diretamente

Regra de segurança:

> **A LLM nunca deve possuir acesso SQL direto nem credenciais do banco.**

O fluxo correto permanece:

```text
LLM
 |
 | identifica intenção
 v
Capability autorizada
 |
 v
CRM-api
 |
 | autorização
 | regra de negócio
 | escopo
 v
resultado estruturado
 |
 v
LLM redige resposta
```

A LLM interpreta e redige.

O CRM-api decide:

- quais dados podem ser consultados;
- qual cliente está em contexto;
- qual representante é responsável;
- quais informações podem ser expostas;
- quais ações podem ser executadas.

---

# 21. Separação entre identidade interna e interlocutor externo

Quando o representante conversa com o robô central:

```text
actor = REPRESENTATIVE
```

Quando o cliente conversa diretamente com a linha do representante e o robô atua, o contexto é diferente:

```text
channel_owner = Representante
counterparty   = Cliente
```

Modelo conceitual:

```text
ConversationContext

representative_user_id
customer_id
contact_id
line_id
phone_number_id
mode
last_human_message_at
last_bot_message_at
last_customer_message_at
```

O sistema está:

> **respondendo em nome do representante, mas para um cliente externo.**

Isso deve permanecer explícito em toda autorização.

---

# 22. Capabilities específicas para atendimento ao cliente

Não é permitido reutilizar automaticamente todas as permissões internas do representante na conversa externa.

Exemplo:

O representante pode internamente consultar:

```text
- toda a própria carteira
- histórico de vários clientes
- margens
- campanhas
- dados administrativos
```

O cliente falando com o robô na linha do representante não ganha esses privilégios.

Devem existir capabilities específicas para contexto externo, por exemplo:

```text
CUSTOMER_GET_CURRENT_PRICE
CUSTOMER_GET_PRODUCT_INFO
CUSTOMER_GET_AVAILABLE_PRICE_LIST
CUSTOMER_GET_OWN_ORDER_STATUS
CUSTOMER_GET_DOCUMENT
CUSTOMER_REQUEST_REPRESENTATIVE
```

E nunca capabilities como:

```text
LIST_REPRESENTATIVE_CUSTOMERS
GET_OTHER_CUSTOMER_HISTORY
GET_INTERNAL_MARGIN
GET_OTHER_CUSTOMER_PRICES
```

Regra:

> **A identidade do canal define em nome de quem o sistema fala; a identidade do interlocutor define o que pode ser revelado.**

---

# 23. Histórico com autoria explícita

O CRM deve conseguir distinguir quem produziu cada mensagem.

Exemplo:

```text
09:15 HUMAN          Carlos envia tabela
09:22 CUSTOMER       João pergunta sobre PUE 20
09:23 HUMAN          Carlos responde
09:25 CUSTOMER       João pergunta preço
09:27 BOT            IA responde com dado do CRM
09:29 CUSTOMER       João pede condição especial
09:29 BOT_HANDOFF    IA transfere para humano
09:31 HUMAN          Carlos assume
```

Essa autoria deve ser preservada para:

- auditoria;
- histórico;
- análise comercial;
- treinamento posterior;
- métricas de automação;
- supervisão;
- investigação de incidentes.

---

# 24. Evolução do conceito do Plano A

A definição do Plano A passa a ser:

> **Plano A — Conversação híbrida na identidade do representante.**

O representante mantém a relação direta com o cliente pelo WhatsApp Business App.

O Gateway observa a conversa por Coexistence e pode, conforme políticas determinísticas:

- permanecer apenas observando;
- fornecer assistência interna ao representante;
- assumir automaticamente respostas permitidas;
- devolver a conversa ao humano;
- suspender imediatamente a automação quando houver intervenção humana.

Durante atuação automática:

- a IA consulta o CRM somente por capabilities autorizadas;
- a resposta sai pela própria linha WhatsApp Business do representante;
- a identidade do cliente limita os dados que podem ser expostos;
- toda ação é auditável.

---

# 25. Princípios adicionais do Plano A híbrido

Adicionar aos princípios arquiteturais do projeto:

11. **Humano sempre prevalece sobre automação.**
12. **Mensagem manual do representante suspende imediatamente o bot naquela conversa.**
13. **A LLM nunca decide sozinha quais dados internos podem ser expostos ao cliente.**
14. **Capabilities de cliente são diferentes das capabilities internas do representante.**
15. **Toda mensagem deve preservar autoria: CUSTOMER, HUMAN, BOT ou SYSTEM/HANDOFF.**
16. **O estado de atendimento pertence à conversa representante ↔ cliente, não apenas ao telefone.**
17. **O robô pode reassumir a conversa apenas por política explícita e auditável.**
18. **O CRM continua sendo autoridade sobre dados e permissões; o Gateway continua sendo autoridade sobre canal e transporte.**
19. **Coexistence permite automação e atendimento humano coexistirem na mesma identidade WhatsApp.**
20. **O objetivo é um copiloto/agente comercial, não substituir silenciosamente o representante.**

---

# 26. Extensão do PoC do Plano A

O PoC deve ganhar etapas adicionais depois da validação básica de Coexistence.

## P8 — Echo de mensagem humana

- representante envia uma mensagem manual pelo WhatsApp Business App;
- Gateway recebe `smb_message_echoes`;
- sistema identifica corretamente:
  - linha;
  - representante;
  - cliente;
  - direção;
  - `wamid`;
  - conteúdo;
- CRM registra a autoria como `HUMAN`.

## P9 — Resposta automática na mesma conversa

- cliente envia pergunta de teste;
- Gateway identifica cliente + representante + linha;
- CRM devolve um dado seguro;
- LLM redige resposta;
- Gateway envia pela linha do representante;
- cliente recebe no mesmo chat;
- CRM registra autoria `BOT`.

## P10 — Handoff automático

- conversa começa em `BOT_ACTIVE`;
- representante envia mensagem manual;
- Gateway recebe echo;
- estado muda para `HUMAN_ACTIVE`;
- qualquer resposta automática pendente é cancelada ou suprimida.

## P11 — Reassunção controlada

Testar pelo menos uma política:

- timeout de inatividade;
- fora do horário;
- ativação explícita.

Confirmar que o bot reassume apenas a conversa correta.

## P12 — Segurança de capabilities

Testar tentativa do cliente de obter dado não autorizado.

Exemplo:

> “Quanto vocês vendem para a empresa XYZ?”

Resultado esperado:

- capability recusada;
- nenhum dado de terceiro consultado ou exposto;
- resposta segura ao cliente;
- evento auditado.

---

# 27. Novo critério de aceite ampliado do Plano A

Além dos critérios anteriores, o Plano A completo será considerado validado quando:

11. mensagens manuais do representante forem observáveis pelo Gateway;
12. mensagens do bot e do humano puderem coexistir na mesma conversa;
13. uma intervenção humana suspender automaticamente a automação;
14. o robô puder reassumir a conversa por política explícita;
15. a autoria de cada mensagem permanecer rastreável;
16. capabilities externas não vazarem permissões internas do representante;
17. a LLM nunca acessar diretamente banco ou credenciais;
18. o CRM conseguir reconstruir a timeline completa cliente ↔ representante ↔ bot.
