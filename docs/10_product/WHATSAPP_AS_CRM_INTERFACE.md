# WhatsApp como interface do CRM-textil

**Natureza:** visão de produto e princípios arquiteturais.  
**Estado:** define papéis canônicos de linha WhatsApp e a direção conversacional do produto. Não cria modelo, migration, contrato, endpoint ou automação.

## Visão de produto

O CRM-textil evolui para ser verdadeiramente conversacional: o representante poderá realizar grande parte do trabalho cotidiano pelo WhatsApp, sem abrir o portal para cada operação. O portal web continua essencial para administração, configuração, auditoria, relatórios, visualizações amplas, filtros complexos e operações administrativas.

Essa visão não transforma qualquer linha WhatsApp em um único canal indistinto. Duas linhas podem ter papéis arquiteturais diferentes e complementares.

## Conceitos canônicos

### `CRM_ASSISTANT_LINE`

Canal conversacional interno pelo qual usuário autorizado — por exemplo, um representante — interage com CRM-textil e sua IA assistente. É a interface diária da pessoa com a plataforma, não um canal externo de atendimento comercial.

Exemplos de uso futuro:

- consultar preço, produto, estoque, carteira, histórico ou clientes inativos;
- receber alertas e resumos de atividades;
- pedir ajuda à IA ou sugerir próxima ação;
- preparar e acompanhar campanha;
- solicitar uma ação comercial estruturada.

A linha corporativa hoje utilizada pela BPTI é apenas a implementação concreta atual desse papel. `BPTI` não pertence ao conceito, ao modelo de domínio nem à arquitetura futura.

### `REPRESENTATIVE_COEXISTENCE_LINE`

Canal comercial externo, vinculado ao representante, usado para comunicação com seus clientes. Pode futuramente suportar atendimento automatizado, atendimento humano pelo WhatsApp Business App, campanhas, respostas a clientes e orquestração humano/bot em Coexistence.

Esse é o papel correspondente ao fluxo Coexistence básico já validado. A validação registrou inbound automatizado, resposta automática, resposta humana pelo App no mesmo número e `smb_message_echoes` observado no Gateway. Ela não torna autoria no CRM, handoff, supressão de bot ou timeline unificada implementados.

## Princípio central congelado

```text
Representante
  → CRM_ASSISTANT_LINE
  → CRM-textil / IA
  → ação estruturada e autorizada
  → REPRESENTATIVE_COEXISTENCE_LINE
  → Cliente
```

`CRM_ASSISTANT_LINE` é a interface interna com a plataforma. `REPRESENTATIVE_COEXISTENCE_LINE` é o canal externo para clientes. Os dois papéis não podem ser confundidos, mesmo que ambos sejam transportados por WhatsApp.

O desenho não é acoplado a BPTI, número, tenant, usuário ou empresa específicos. Deve permitir futuras múltiplas instâncias de cada papel.

## IA como assistente do representante

A IA atua como copiloto dentro da `CRM_ASSISTANT_LINE`: interpreta linguagem natural, identifica intenção, consulta contexto autorizado por meio do CRM, resume dados, sugere respostas, prepara mensagens/campanhas e sugere próximas ações.

Mesmo quando o representante conduz manualmente um cliente pela `REPRESENTATIVE_COEXISTENCE_LINE`, pode consultar a IA pela linha assistente. Exemplo: diante de “Tem 200 metros do 75/36 azul?”, o representante pergunta ao assistente “Quanto temos do 75/36 azul e qual o preço atual?”; a resposta volta pela `CRM_ASSISTANT_LINE`, sem a IA falar diretamente com o cliente.

## Autoridade e segurança

| Componente | Responsabilidade |
|---|---|
| IA | interpretar, identificar intenção, redigir, sugerir e organizar contexto |
| CRM | autenticar usuário, aplicar tenant/RBAC, resolver representante e carteira, validar escopo, consultar dados, estruturar ações, manter estado, exigir confirmação e auditar |
| Gateway | controlar canal WhatsApp, resolver linha técnica, transportar mensagens, proteger credenciais, integrar Meta e processar webhooks |

A IA não é autoridade final de execução. Ela não decide sozinha público final, sender, linha técnica, permissão, envio em lote, regra comercial ou ação irreversível.

## Três níveis de ação

| Nível | Exemplo | Regra |
|---|---|---|
| `CONSULTA` | “Qual o preço do 75/36?” | pode responder diretamente, dentro do escopo autorizado |
| `PREPARAÇÃO` | “Monte uma campanha para meus clientes de poliéster.” | CRM interpreta, resolve público e conteúdo/template, calcula prévia; não envia |
| `EXECUÇÃO` | “Pode enviar.” | requer ação pendente válida, autorização, escopo/sender/destinatários/conteúdo congelados, confirmação explícita e auditoria |

## Exemplo canônico: campanha iniciada pela linha assistente

```text
Representante: “mande mensagem para todos os meus clientes de poliéster
sobre o novo preço do 75/36 Trama”
  → CRM_ASSISTANT_LINE
  → Gateway identifica a origem
  → CRM identifica ator, tenant e carteira
  → IA interpreta intenção, segmento, artigo e finalidade
  → CRM resolve público elegível e prepara campanha
  → CRM apresenta prévia
  → representante confirma
  → CRM congela a ação
  → Gateway resolve REPRESENTATIVE_COEXISTENCE_LINE
  → Gateway executa envio
  → clientes recebem pela identidade comercial do representante
```

Quando aplicável, a preparação inclui template aprovado da WhatsApp Business Platform. Uma ordem em linguagem natural não dispensa seleção de template, consentimento, confirmação ou regras do canal.

## Capacidades atuais e futuras

| Situação | Capacidades |
|---|---|
| **Implementado** | fluxo conversacional atual em linha corporativa concreta, consultas/capabilities já publicadas no Gateway e vertical slice de onboarding Coexistence. |
| **Direção futura** | `CRM_ASSISTANT_LINE` como interface principal do representante para consultas, preparação e acompanhamento de ações comerciais. |
| **Futuro dependente de F6/F7** | envio de campanha pelo vínculo do representante; autoria `HUMAN` projetada no CRM; `HUMAN_ACTIVE`/`BOT_ACTIVE`; handoff, supressão de bot, reassunção e timeline unificada. |

O estado atual de campanhas está em [Campanhas de WhatsApp](WHATSAPP_CAMPAIGNS.md). A evidência e os limites do onboarding Coexistence estão em [WhatsApp Coexistence — jornada ponta a ponta](../40_delivery/WHATSAPP_COEXISTENCE_END_TO_END.md).

## Relação com documentos existentes

- [Coexistence do representante](../30_architecture/WHATSAPP_REPRESENTATIVE_COEXISTENCE.md) detalha o papel externo e seus limites arquiteturais.
- [F7 — Conversação híbrida](../40_delivery/F7_WHATSAPP_HYBRID_CONVERSATION.md) continua sendo o blueprint futuro de autoria, handoff e modos de conversa.
- [Campanhas de WhatsApp](WHATSAPP_CAMPAIGNS.md) descreve o motor comercial único, preparação e integração futura com o Gateway.
