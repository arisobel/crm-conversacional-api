# F6 — Campanhas de WhatsApp

Plano de entrega da frente **D** do [backlog](../00_meta/09_backlog.md), sobre a
[especificação de campanhas](../10_product/WHATSAPP_CAMPAIGNS.md), o
[modelo-alvo §7](../20_domain/DOMAIN_MODEL_TARGET.md) e o
[ADR-028](../00_meta/08_decisions_log.md). Registrado em 2026-09-02 a partir do
roteiro aprovado de campanhas. **Nada aqui está implementado; o envio de
campanhas não existe no CRM-API.**

## Regra arquitetural central

O CRM-API **não envia mensagens à Meta** e não acessa o banco do Gateway.

| Componente | Responsabilidade |
|---|---|
| **CRM-API** | Clientes, contatos, representantes, carteira, permissões, grupos/segmentos, prévia comercial, rascunhos, auditoria e projeção do histórico |
| **Gateway** (`arisobel/whatsapp-webhook-caprover`) | Meta Cloud API, templates operacionais, consentimento/opt-out, fila e ritmo, envio efetivo, webhooks e estados técnicos da mensagem |
| **Meta** | Aprovação de templates, janela de 24 horas e entrega no canal |
| **CKJ-app** | Referência de UX para lista e detalhe de campanhas. **Não** é fonte de contrato, banco ou código |

Toda regra comercial e de carteira nasce no CRM. Toda ação de canal nasce no
Gateway. As regras de negócio fechadas — carteira do representante, alçada de
`ADMIN`/`MANAGER`, público determinístico, `product_groups` como eixo, template
Meta fora da janela, consentimento no Gateway, idempotência de toda escrita —
estão no ADR-028 e na especificação; este plano não as repete, só as sequencia.

## Resultado esperado ao final

Um representante autenticado monta uma campanha a partir de critérios
estruturados, revisa uma prévia determinística restrita à própria carteira,
salva um rascunho auditável e o confirma; o Gateway executa o envio, revalida o
consentimento antes de cada mensagem e devolve eventos que atualizam o detalhe
da campanha e a ficha de cada cliente alcançado. `ADMIN` e `MANAGER` acompanham
o tenant inteiro. Nada disso é acessível por texto livre nem por escolha de
público feita por LLM.

## Sequência

```text
F6.0 decisões e contrato conceitual ─┐
F6.1 modelo de campanha no CRM ──────┼─ F6.3 portal de campanhas ─┐
F6.2 resolvedor de audiência ────────┘                            ├─ F6.5 comandos conversacionais
                     F6.0 fechada ── F6.4 integração com o Gateway┘
```

F6.1 e F6.2 podem começar imediatamente e não dependem de F6.0 — elas não criam
integração externa. F6.3 entrega o portal com a confirmação **bloqueada ou
simulada**. F6.4 só começa com F6.0 fechada. F6.5 é o último incremento e usa o
motor já validado pelo portal.

Correspondência com o backlog: F6.0 ≈ pendências de D0/D1; F6.1 ≈ D2 (modelo);
F6.2 ≈ D1 (filtros) + D2 (prévia); F6.3 ≈ D4; F6.4 ≈ D3; F6.5 ≈ D5. Os casos
comerciais de D6 (aviso de queda de preço) atravessam F6.2 em diante.

---

## F6.0 — Fechamento de decisões e contrato

**Ainda não implementar envio.** Entregas, todas documentais:

- [ ] Corrigir referências documentais ao Gateway e registrar a versão/commit
      consultado — a cópia local analisada não contém
      `whatsapp-marketing-broadcast-v1.md` nem `meta_whatsapp_campaigns.js`.
- [ ] Definir um único vocabulário para os endpoints internos CRM ↔ Gateway.
      Não criar endpoint de integração definitivo antes desta decisão.
- [x] Limite de destinatários que exige confirmação nominal no portal:
      **350**, decidido em 2026-09-02 (ADR-029). Configurável, padrão 350;
      avaliado sobre o público congelado no rascunho.
- [ ] Decidir a origem válida do opt-in inicial de marketing.
- [ ] Decidir a alçada de `ADMIN`/`MANAGER` para criar, confirmar e cancelar em
      nome de outra carteira.
- [ ] Definir retenção LGPD de rascunhos, destinatários e projeções, e a relação
      com `CRM_INTERACTION_RETENTION_DAYS` (Q3).
- [ ] Definir propriedade e visibilidade das listas de julgamento.

Critério de saída: contrato conceitual e decisões de negócio registrados em
`docs/` — ADRs novos ou complemento do ADR-028.

---

## F6.1 — Modelo de campanha no CRM — implementada em 2026-09-02

**Migração `0015`.** Duas tabelas novas, nada existente é alterado — como a
`0011`, é das migrações mais baratas da série. Verificada por
`tests/test_whatsapp_campaigns.py` (19 testes); a suíte inteira está em 467
verdes.

Entrega:

- `whatsapp_campaigns` e `whatsapp_campaign_recipients` conforme o
  [modelo-alvo §7](../20_domain/DOMAIN_MODEL_TARGET.md), com os enums
  `whatsapp_campaign_status` e `whatsapp_campaign_recipient_status`.
- `WhatsappCampaignRepository`, com o escopo aplicado **no repositório** — como
  no `CustomerPortfolioRepository`, e não na rota, que ainda nem existe.
- `WhatsappCampaignService`: criar rascunho idempotente, consultar com recorte
  por papel e cancelar rascunho, tudo auditado em `audit_log`.
- Nenhuma chamada à Meta ou ao Gateway. Os campos `gateway_*` nascem nulos e
  são o lugar reservado para a correlação da F6.4.

**Quatro decisões tomadas na implementação:**

**Nenhum papel cria campanha em nome de outra carteira, `ADMIN` inclusive.** A
alçada é pendência da F6.0, e a alternativa — abrir um caminho permissivo
"temporário" — criaria um poder que a decisão depois teria de revogar, sobre
rascunhos que já existiriam. `ADMIN` e `MANAGER` já **leem** o tenant inteiro;
o que não existe é caminho de código para escreverem fora da própria carteira.

**A unicidade do destinatário são dois índices parciais, não um `UNIQUE` de
três colunas.** No PostgreSQL uma coluna nula não deduplica, e o
`UNIQUE(campaign_id, customer_id, contact_id)` que o modelo-alvo propõe
deixaria passar duas exclusões do mesmo cliente sem contato elegível. Ficam
`ux_wcr_contact` (quando há contato) e `ux_wcr_customer_without_contact`
(quando não há).

**A validação inteira acontece antes de qualquer `add`.** Um rascunho com uma
linha fora da carteira não é gravado pela metade: o teste confere que a tabela
continua vazia depois da recusa.

**O modelo não usa o atalho `index=True`.** Ele geraria índices que a `0015`
não cria, e nomes (`ix_..._campaign_id`) diferentes dos migrados — exatamente a
divergência que `ops/ci/check_pg_schema.py` existe para impedir. Modelo e
migração declaram hoje o mesmo conjunto, conferido nome a nome.

Aceite — verificado por `tests/test_whatsapp_campaigns.py`:

- Um representante não monta rascunho com cliente de outra carteira, e a recusa
  não grava nada.
- `ADMIN` sem clientes próprios também é recusado — a pendência da F6.0 não é
  antecipada por código.
- Reentrega do mesmo comando não abre segunda campanha; a corrida é decidida
  pela unicidade do banco, com `SAVEPOINT` para recuperar a que venceu.
- A fotografia sobrevive: renomear o cliente depois não altera o
  `recipient_snapshot` do que já foi revisado.
- Representante recebe o mesmo erro para campanha alheia e campanha
  inexistente, e a lista dele não a inclui.
- O filtro por representante é ignorado para `REPRESENTATIVE` — o recorte do
  papel prevalece, como o `owner_user_id` ignorado no cadastro de cliente (R2).
- Isolamento de tenant exercitado **no repositório isolado**, sem passar por
  rota nem serviço.
- Cancelar rascunho é idempotente e grava uma única entrada na trilha; campanha
  confirmada não é cancelável por este fluxo — isso é F6.4, com o Gateway.
- Exclusão exige motivo, linha sem contato só existe como exclusão, e rascunho
  inteiramente excluído é recusado.

Pendências: aplicar a `0015` contra PostgreSQL — ela roda sozinha no próximo
deploy pelo `docker-entrypoint.sh`; confirmar nos logs de start. A reversão
**falha de propósito** se houver campanha fora de `DRAFT`/`CANCELLED`: apagar
as tabelas perderia o registro do que foi aprovado.

Critério de saída **atingido**: é possível criar e consultar um rascunho
auditável localmente, sem que nada seja enviado.

---

## F6.2 — Resolvedor determinístico de audiência — implementada em 2026-09-02

**Sem migração.** `AudienceRepository` e `AudienceResolver`, verificados por
`tests/test_campaign_audience.py` (24 testes). A suíte inteira está em 491
verdes.

Entrega:

- `AudienceCriteria`, critérios estruturados com forma canônica estável — é ela
  que vira o `criteria_snapshot` do rascunho.
- `AudienceResolver.resolve`, que aplica a ordem obrigatória de filtragem e
  devolve a prévia com os três baldes descritos abaixo.
- `AudiencePreview.to_draft_recipients()`, o encaixe com a F6.1: a prévia vira
  o público congelável sem que ninguém redigite a lista.
- Filtro de carteira por grupo, composição/fibra, artigo preferido e UF — o
  item que estava aberto em D1.

**Cinco decisões tomadas na implementação:**

**A prévia tem três baldes, não dois.** Elegíveis, excluídos e **não
classificados**. O terceiro existe por causa do ADR-027: um cliente cujos
artigos preferidos não têm composição cadastrada não é "cliente sem poliéster",
é cliente sobre quem não dá para afirmar nada. Ele não vira destinatário, não
conta como exclusão comercial e some da prévia no dia em que alguém completar o
cadastro. Sem esse balde, a lacuna de cadastro encolheria o público em silêncio
— exatamente o defeito que esta fase existe para impedir.

**Uma mensagem por cliente, com política explícita de contato.** O contato
principal ganha; um único contato ativo é escolha inequívoca; vários ativos sem
principal é ambiguidade real e vira exclusão `CONTATO_AMBIGUO`. Eleger um por
ordem de cadastro mandaria a mensagem por acaso, e o modelo-alvo pede política
explícita justamente para que ninguém receba duas vezes nem por engano.

**Critério desconhecido levanta erro; nunca é ignorado.** `from_mapping` recusa
chave que o domínio não modela. `porte`, `curva_abc`, `potencial` e
`lista_julgamento` têm mensagem própria — dizer "ainda não foi modelado" é
acionável, dizer "desconhecido" faz parecer erro de digitação. Grupo, fibra ou
artigo inexistente também **falha**, em vez de devolver um público menor sem
explicar por quê.

**Critério vazio não significa "toda a carteira".** Alcançar todo mundo é
escolha explícita, feita com `include_entire_portfolio`, e não o que sobra de
um formulário em branco.

**Dentro de um eixo os valores somam; entre eixos de produto eles se cruzam.**
Dois grupos trazem os artigos de qualquer um dos dois; grupo mais fibra traz os
artigos que são as duas coisas. A semântica está documentada no dataclass
porque precisa ser previsível para quem monta a campanha.

Aceite — verificado por `tests/test_campaign_audience.py`:

- Um representante jamais vê destinatário fora da própria carteira, e o
  `ADMIN` tampouco — a alçada continua pendente da F6.0.
- Isolamento de tenant e de carteira exercitado **no repositório isolado**,
  sem passar por rota nem serviço.
- Cliente sem contato ativo e cliente com contatos ambíguos aparecem como
  exclusão com motivo, não somem da prévia.
- Cliente com artigo sem composição sai como não classificado, e não como
  ausência da fibra.
- Grupo **não** produz não classificado: não estar num grupo é fato curado por
  alguém, não lacuna.
- Piso de percentual de fibra recorta de verdade (92% entra com piso 60, sai
  com piso 95).
- A mesma prévia, pedida duas vezes, devolve a mesma lista na mesma ordem.
- A prévia alimenta o rascunho da F6.1, e os não classificados não entram nele.

A ordem obrigatória de filtragem implementada:

1. tenant;
2. papel e usuário autenticado;
3. carteira (`owner_user_id`) quando for representante;
4. clientes e contatos ativos;
5. filtros comerciais existentes — `product_groups`, produtos preferenciais,
   fibra/composição (migrações `0013`/`0014`);
6. elegibilidade externa de consentimento, **somente** quando o contrato com o
   Gateway estiver pronto (F6.4).

O serviço retorna: lista nominal de clientes e contatos; contagens por inclusão
e exclusão; motivo de cada exclusão; critérios normalizados; erro claro e
orientado ao usuário para critério inexistente ou ambíguo — nunca um público
"plausível" por aproximação.

Limites herdados de D0/D1, todos respeitados: `product_families` não substitui
grupos; porte, curva ABC e potencial **não são inferidos** — só entram como
filtro depois de existirem como atributo declarado com regra explícita; produto
sem composição é não classificado, não negativa implícita.

O passo 6 é o único não implementado, e de propósito: consentimento é do
Gateway e chega na F6.4. Enquanto isso, a prévia não afirma nada sobre
consentimento — não o presume concedido nem negado.

Critério de saída **atingido**: prévia reproduzível, com escopo de carteira
provado por teste no repositório isolado.

---

## F6.3 — Portal de campanhas — implementada em 2026-09-02

**Sem migração.** Roteador próprio em `web/campaign_routes.py`, três telas e a
seção na ficha do cliente. Verificada por `tests/test_portal_campaigns.py`
(16 testes). A suíte inteira está em 507 verdes.

Entrega:

| Tela | Rota | Conteúdo |
|---|---|---|
| Lista | `/portal/campaigns` | Campanhas do escopo, filtro por situação |
| Nova | `/portal/campaigns/nova` | Critérios a partir do que o cadastro tem |
| Revisão | `POST /portal/campaigns/previa` | Os três baldes, nominalmente; não grava |
| Detalhe | `/portal/campaigns/{id}` | Snapshots, destinatários, cancelamento |
| Ficha do cliente | seção nova | De quais campanhas ele participou |

**Cinco decisões tomadas na implementação:**

**Não existe botão de confirmar, e a tela diz por quê.** A campanha para no
rascunho. Nenhum estado é apresentado como "enviado", e o detalhe explica que
`PENDING` ali significa "congelado no rascunho" — não há fila de envio no CRM.

**O template não é escolhido no portal.** O catálogo de templates aprovados na
Meta é do Gateway e não existe aqui; o `template_snapshot` grava
`{"status": "PENDENTE_CATALOGO_GATEWAY"}`. A alternativa — um campo de texto
para digitar o nome do template — fabricaria uma referência que a Meta não
aprovou, e a tela ficaria mentindo sobre estar pronta.

**O rascunho é montado re-resolvendo os critérios, não a partir da lista
revisada.** Transportar a lista criaria uma segunda fonte de verdade capaz de
divergir da primeira sem ninguém perceber. O que a revisão garante é que a
pessoa viu o resultado daqueles critérios; o que o rascunho congela é o
resultado deles no instante da criação. Um teste força destinatários alheios no
POST e confirma que eles são ignorados.

**Erro de critério volta na própria resposta, não pela query string.** As
mensagens do resolvedor são a informação útil ("porte ainda não é atributo do
cliente") e não cabem num código. Como a página é devolvida no POST, o texto
não viaja pela URL e não abre o canal de injeção que `messages.py` evita. A
exceção é `InvalidStateCode`, cuja mensagem é interna e em inglês: essa usa o
código `uf-invalida`, respeitando o aceite de R6a.

**`ADMIN` e `MANAGER` leem o tenant e não cancelam rascunho alheio.** O botão
não aparece e o POST forjado não tem efeito — a alçada continua sendo pendência
da F6.0.

**Um defeito encontrado rodando o app, que os testes não pegaram:** a tela
mostrava `product_group_ids: ['1a25b79f-…']`, com a chave técnica e o UUID
crus. O snapshot continua guardando o id — é ele que segue verdadeiro se alguém
renomear o grupo —, mas a tela passou a exibir rótulo e nome
(`criterios_legiveis`). Há teste travando isso agora.

Aceite — verificado por `tests/test_portal_campaigns.py`:

- A prévia não grava nada; a lista de campanhas continua vazia depois dela.
- Cliente de outra carteira não aparece na prévia nem na lista.
- Destinatário forjado no POST é ignorado: o público congelado é o do
  resolvedor.
- Mesma chave de idempotência não cria duas campanhas; POST sem CSRF não cria
  nenhuma.
- Representante recebe "não encontrado" para campanha alheia, igual a
  inexistente.
- Gestão acompanha o tenant, mas não vê nem exerce o cancelamento alheio.
- UF inválida aparece em português, e a mensagem interna em inglês não vaza.
- Grupo inexistente explica o motivo, em vez de devolver lista vazia.
- A campanha aparece na ficha do cliente, e a ficha sem campanha diz isso.

Pendências: a revisão nominal acima de 350 (ADR-029) é hoje apenas um **aviso**
na tela — não há confirmação a bloquear enquanto a F6.4 não existir. O filtro da
lista por representante, template e segmento fica para quando houver volume.

Critério de saída **atingido**: o representante constrói e revisa a campanha, e
a gestão acompanha o tenant.

A sequência original planejada, para referência:

1. lista de campanhas por período, situação, representante, template e segmento;
2. criar prévia de audiência;
3. revisar critérios e destinatários;
4. criar rascunho;
5. detalhe e acompanhamento — público previsto, elegível, enviados, entregues,
   lidos, falhos e excluídos;
6. referência da campanha na ficha/timeline do cliente, com navegação
   campanha → ficha.

A confirmação ficou **bloqueada**, não simulada: não existe botão nem rota que
a exerça. Simular criaria um estado `CONFIRMED` que nada honraria, e a próxima
pessoa teria de descobrir sozinha que aquilo não significava nada.

---

## F6.4 — Contrato e integração com o Gateway

Só começa com F6.0 fechada. Fluxos mínimos:

1. CRM consulta o catálogo de templates permitidos no Gateway;
2. CRM solicita/recebe prévia de elegibilidade por consentimento;
3. CRM confirma a campanha e envia comando assinado e idempotente ao Gateway;
4. Gateway devolve a identificação de correlação da campanha;
5. Gateway envia eventos de status ao CRM (`PENDING`, `SENT`, `DELIVERED`,
   `READ`, `FAILED` e resposta);
6. CRM atualiza projeção e ficha do cliente de forma idempotente.

Cancelar afeta apenas rascunho, campanha não iniciada ou a parte pendente; o
que a Meta já aceitou é fato histórico.

Testes obrigatórios de integração:

- repetição de confirmação após timeout;
- evento duplicado;
- evento fora de ordem;
- consentimento revogado entre prévia e envio;
- cancelamento com parte dos destinatários já enviada;
- tentativa de representante alcançar carteira de outro representante.

Critério de saída: a campanha confirmada é executada exclusivamente pelo
Gateway e aparece corretamente no CRM.

---

## F6.5 — Comandos conversacionais no WhatsApp

Último incremento; usa o motor já validado pelo portal. Exemplo:

> "Enviar a promoção do fio 75/36 para meus clientes de poliéster."

- Gateway/LLM: reconhece a intenção e extrai **apenas slots declarados**;
- CRM: resolve audiência, valida carteira e cria prévia/rascunho;
- usuário: confirma explicitamente;
- Gateway: executa somente comando allowlisted e confirmado.

As capabilities candidatas (`CRM_PREVIEW_WHATSAPP_CAMPAIGN_AUDIENCE`,
`CRM_CREATE_WHATSAPP_CAMPAIGN_DRAFT`, `CRM_CONFIRM_WHATSAPP_CAMPAIGN`,
`CRM_CANCEL_WHATSAPP_CAMPAIGN`, `CRM_GET_WHATSAPP_CAMPAIGN_STATUS`) estão na
[especificação](../10_product/WHATSAPP_CAMPAIGNS.md#evolução-conversacional).
Nenhuma entra no manifesto do Gateway sem executor local, contrato testado,
confirmação e idempotência — ADR-022 a ADR-026.

Critério de saída: o fluxo conversacional produz exatamente o que o portal
produziria com os mesmos critérios, e nada além.

---

## Regras transversais para quem implementa

- Ler antes: [WHATSAPP_CAMPAIGNS.md](../10_product/WHATSAPP_CAMPAIGNS.md),
  [backlog D](../00_meta/09_backlog.md), ADRs e
  [API_CONTRACT](../30_architecture/API_CONTRACT.md).
- Não introduzir envio direto à Meta a partir do CRM-API; não alterar o Gateway
  neste repositório.
- Não tratar `customer_interactions` como fonte de verdade de consentimento nem
  da janela de 24 horas.
- Não inferir filtros; sem critério modelado, erro orientado ao usuário.
- Toda escrita com autenticação, autorização, auditoria e idempotência.
- Cada fase entra com migração reversível, testes e atualização de
  `07_progress.md` e `09_backlog.md`.

## Definição de pronto da primeira entrega

A primeira entrega (F6.1 + F6.2, início de F6.3) está pronta quando um
representante autenticado gera uma prévia de campanha com filtros válidos, vê
nominalmente apenas a própria carteira, salva um rascunho auditável e o
consulta no portal — **sem que nenhuma mensagem seja enviada**.
