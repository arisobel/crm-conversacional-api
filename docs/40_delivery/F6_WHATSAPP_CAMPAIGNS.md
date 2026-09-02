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

## F6.2 — Resolvedor determinístico de audiência

Serviço de leitura que recebe critérios **estruturados** e devolve uma prévia
reproduzível: o mesmo conjunto de critérios produz a mesma prévia no mesmo
contexto de dados. Ordem obrigatória de filtragem:

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

Limites herdados de D0/D1: `product_families` não substitui grupos; porte,
curva ABC e potencial **não são inferidos** — só entram como filtro depois de
existirem como atributo declarado com regra explícita; produto sem composição é
não classificado, não negativa implícita.

Aceite mínimo, com testes dedicados:

- Um representante jamais vê destinatário fora da própria carteira, verificado
  na camada de repositório, sem passar por rota nem serviço.
- Isolamento de tenant em toda consulta.
- Critério não modelado devolve erro orientado, não resultado vazio silencioso.

Critério de saída: prévia reproduzível, com escopo de carteira provado por
teste.

---

## F6.3 — Portal de campanhas

Experiência inspirada no CKJ-app, sobre o domínio do CRM. Sequência mínima de
telas:

1. lista de campanhas por período, situação, representante, template e segmento;
2. criar prévia de audiência;
3. revisar critérios e destinatários;
4. criar rascunho;
5. detalhe e acompanhamento — público previsto, elegível, enviados, entregues,
   lidos, falhos e excluídos;
6. referência da campanha na ficha/timeline do cliente, com navegação
   campanha → ficha.

Nesta fase a confirmação permanece **bloqueada ou simulada** até F6.4. Nunca
apresentar "enviado" quando existe apenas rascunho.

Critério de saída: o representante constrói e revisa sua campanha;
`ADMIN`/`MANAGER` acompanham o tenant conforme a alçada decidida em F6.0.

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
