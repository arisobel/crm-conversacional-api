# Manifesto de capacidades por ator no WhatsApp

Desenho aprovado em 2026-08-16. Substitui o manifesto único do ADR-012 por um
manifesto resolvido por contato, no envelope canônico que o Gateway define para
novos aplicativos de negócio.

Este documento descreve o alvo. **Nada aqui está implementado.**

As afirmações sobre o Gateway foram medidas em
`https://github.com/arisobel/whatsapp-webhook-caprover`, commit `dbd2d75` de
2026-08-14, com working tree local em `C:\projetos\whatsapp-webhook-caprover`.
Não use a cópia em `.work-gateway/`: ela é um clone antigo, e a primeira versão
deste documento afirmou por causa dela que o consumidor do roster não existia.

## Problema

O manifesto de interação de hoje é uma constante do processo: a função
`get_interaction_capabilities()` não recebe argumento, não consulta o banco e
descarta o `tenant_slug` que o HMAC já validou. Representante e cliente recebem
exatamente as mesmas intenções, e a diferenciação de acesso não tem por onde
existir.

## Decisões de partida

| # | Decisão |
|---|---|
| D1 | Representante e cliente conversam pela **mesma linha e o mesmo fluxo**. A diferença de papel vive no manifesto, nunca no roteamento. |
| D2 | O representante **consulta dados de cliente da carteira dele**, e só dela. |
| D3 | O `ADMIN` do tenant administra representantes. Não existe nível acima. |
| D4 | Escrita entra no primeiro corte: **pré-cadastro de cliente com preferências de material**. |
| D5 | **Quem o Gateway atende é decidido lá para o representante e aqui para o cliente.** O telefone do representante é autorizado à mão no painel do Gateway; a lista automática do CRM continua sendo só de clientes. |
| D6 | A mensagem de representante vira **histórico do próprio representante**, não da ficha de um cliente. |
| D7 | O vocabulário cresce **por operação, não por deploy**: ele vive no banco e é editado no portal, alimentado por um relatório do que o robô não entendeu. |
| D8 | `ADMIN` e `MANAGER` no WhatsApp recebem o manifesto de representante. Nenhuma ação administrativa passa pelo canal. |

O princípio que amarra todas: **o WhatsApp nunca concede alçada que o portal já
não conceda — ele só antecipa digitação.**

## Por que o envelope canônico, e não evoluir o endpoint atual

Foram avaliadas duas saídas:

**(A)** Evoluir `GET /internal/interaction-capabilities` para receber o telefone
e devolver um bloco `actor`.

**(B)** Adotar `POST /api/integrations/whatsapp/v1/capabilities/manifest`, no
envelope `business-capability-manifest/v1`.

Adotou-se **(B)**. O Gateway já tem para esse envelope especificação, JSON
Schema, fixture compartilhada, ADR e testes de contrato — inclusive
`GW-062`, "testes de permissões diferentes por ator", concluído. O `actor
{ id, role }` que falta aqui é campo nativo lá. E o backlog do Gateway já prevê
em `GW-015` a compatibilidade ou migração explícita do manifesto CRM atual: o
formato de hoje já está marcado para sair. A opção (A) evoluiria, mexendo num
contrato que roda em produção, um formato que só o CRM fala e que teria de ser
migrado de novo depois.

(B) também torna a restrição de escrita expressável sem extensão: `mode`,
`requires_confirmation` e `idempotency` são campos do envelope.

### A extensão que (B) exige antes de valer

O v1 mínimo admite somente `schema_version`, `provider`, `actor`,
`channel_context`, `expires_in_seconds`, `capabilities` e `help_message`, e
rejeita campo adicional. Não há lugar para aliases, exemplos ou slots.

Mas o resolvedor determinístico do Gateway (`resolveCrmIntentByRules`) lê
`manifest.intents[].aliases`, e `SEARCH_CURRENT_PRICE_LIST_ITEMS` depende do
slot `product_query`. Adotar o v1 literal **desligaria a resolução por regra e
entregaria toda a classificação à LLM** — o contrário do que o ADR-012
estabelece, que existe justamente para não codificar vocabulário comercial no
Gateway.

Por isso (B) é condicionada a estender o v1 com `vocabulary` e `slots` por
capacidade. Sem esse acordo prévio, a migração é regressão.

E o pedido é maior do que parece, porque nada do v1 é genérico ainda. Em
`origin/main`:

- `isValidCkjCapabilityManifest` exige `provider === "ckj_api"`, valida a ação
  contra o conjunto `CKJ_CAPABILITY_ACTIONS` e aplica `hasOnlyKeys` em todos os
  níveis. Campo adicional é recusado **em código**, não só na especificação.
- `resolveCrmIntentByRules` procura literalmente os identificadores
  `LIST_CURRENT_PRICES` e `SEARCH_PRODUCT`, e traz embutida a expressão
  `\d{2,3}/\d{1,3}` do vocabulário têxtil. A resolução determinística genérica
  do `GW-021` não existe; a que existe é específica do CRM e presa a dois
  identificadores.

Consequência prática: as capacidades novas de representante não teriam
resolução por regra nenhuma, em qualquer formato de manifesto, enquanto o
`GW-021` não for feito. Elas cairiam direto na LLM.

### O que a extensão não resolve, e a decisão que faltava

`vocabulary` e `slots` devolvem ao CRM a lista de sinônimos. Não devolvem o
reconhecimento de **identificador**: hoje `75/36` é casado por
`\b\d{2,3}\s*/\s*\d{1,3}\b`, escrita dentro do Gateway, e nenhum campo de texto
declarativo expressa isso.

Transportar a expressão no manifesto foi recusado do lado do Gateway, e a recusa
é correta: regex vinda de origem remota é ReDoS e superfície de injeção, e o
contrato proíbe transportar código, template ou função.

A saída adotada é **tipo de slot nomeado**: o slot declara `kind`, e o Gateway
guarda localmente o casador de cada tipo registrado.

```json
"slots": [{ "id": "product_query", "required": true, "kind": "product_code" }]
```

O CRM declara **qual** tipo, nunca o padrão. Tipo desconhecido é recusado como
qualquer ação desconhecida.

`kind` é opcional, e a maioria dos slots aqui não declara nenhum. O enum
pertence ao Gateway (ADR-026): cada tipo novo custa um deploy lá mais a
atualização coordenada do schema compartilhado, então a regra é **`vocabulary`
primeiro, `kind` por exceção**. E ele ainda é inerte — quem vai consumi-lo na
resolução é o `GW-021`, aberto —, o que a W6 precisa considerar.

Consequência aceita, e ela é honesta em vez de silenciosa: o conhecimento de que
código têxtil tem a forma `NN/NN` continua morando no Gateway, o que contraria a
letra do ADR-012. A diferença é que hoje isso é acidental e invisível — uma
regex solta no meio de uma função — e passa a ser um tipo registrado, nomeado e
revisável, que uma segunda aplicação pode reusar ou recusar.

Se um dia aparecer um segundo formato de identificador, a alternativa é uma
descrição declarativa de dígitos e separadores, compilada localmente com
quantificadores limitados — dados, não padrão. Não se justifica para um formato
só.

### Limites que o validador do v1 impõe

Medidos no código, não na especificação:

| Regra | Efeito no desenho |
|---|---|
| `expires_in_seconds` entre 1 e **900** | O TTL de 30 minutos do ADR-012 não cabe. O teto é 15 minutos. |
| `capability.id === capability.action` | Não é possível manter `id: LIST_CURRENT_PRICES` com `action: GET_CURRENT_PRICE_LIST`. Sob o v1, os dois viram a ação. |
| `actor.id` casa `^[a-f0-9]{24}$` | Exatamente 24 caracteres hexadecimais — 96 bits, nem mais nem menos. |
| `hasOnlyKeys` em todos os níveis | `vocabulary` e `slots` precisam entrar nos conjuntos de chaves permitidas, ou o manifesto inteiro é recusado. |

O terceiro limite carrega uma dívida do Gateway, e não uma regra de contrato:
`^[a-f0-9]{24}$` é a forma de um `ObjectId` do MongoDB, herdada do CKJ e escrita
como se fosse genérica do envelope. O `public_ref` da ADR-023 casa com ela por
construção, então nada trava aqui — mas a terceira aplicação a adotar o padrão
vai esbarrar nela sem entender a origem. Registrado como dívida do outro lado.

### Limites acordados na implementação da extensão

Fixados do lado do Gateway em `e122bb6`, e espelhados aqui para que os dois
repositórios não divirjam em silêncio:

| Regra | Valor |
|---|---|
| `required` dentro de cada slot | obrigatório, sem padrão implícito |
| `id` de slot | `^[a-z][a-z0-9_]{0,39}$`, único dentro da capacidade |
| Alias ou exemplo em branco | recusado — casaria com qualquer mensagem |
| Teto de aliases | 32, com 80 caracteres cada |
| Teto de exemplos | 16, com 240 caracteres cada |
| Teto de slots | 16 por capacidade |
| `vocabulary` e `slots` | por capacidade, nunca no topo do manifesto |
| `schema_version` | continua `v1` — campo aditivo e opcional não sobe versão |

Os identificadores de slot deste desenho — `product_query`, `customer_query`,
`customer_legal_name`, `customer_state_code`, `customer_whatsapp` e
`preferred_products_text` — já obedecem ao formato.

**O nome do slot é contrato, e o validador não o cobre.** O executor do Gateway
lê `resolution.slots.product_query` por nome literal; um manifesto que chamasse o
mesmo slot de `produto` passa por toda a validação e chega ao executor com o
campo vazio. É a única regra load-bearing sem guarda automática dos dois lados —
registrada aqui para não ser redescoberta por acidente, e listada como pedido ao
Gateway (registrar os IDs de slot esperados por ação, do mesmo jeito que `kind` é
registrado).

**O ruído gramatical é problema de quem recebe, não só de quem extrai.** O
resolvedor genérico preenche o slot com o resto da mensagem, artigo incluso:
`"quanto está o PUE 20"` produz `o PUE 20`. Como o casamento exige **todos** os
termos, aquele `o` fazia a busca não encontrar um artigo que existe. O
`search_tokens` descarta artigos e preposições — e só quando sobra algo, para que
uma mensagem que seja apenas `"de"` não vire busca vazia casando com o catálogo
inteiro. A defesa fica no CRM de propósito: vale para qualquer versão do Gateway
e para qualquer consumidor futuro do contrato.

## Resolução do ator

Um serviço único, `resolve_whatsapp_actor(tenant, phone)`, sobre o telefone já
canonizado:

| O telefone casa com | Ator | `actor.role` |
|---|---|---|
| `users` ativo, qualquer papel | representante | `representante` |
| `customer_contacts` ativo de cliente ativo | cliente | `cliente` |
| os dois | **recusa**, `409` | — |
| nenhum | `404` | — |

**`ADMIN` e `MANAGER` no WhatsApp recebem o manifesto de representante.**
Administração acontece no portal, com sessão, CSRF e auditoria. Um canal cuja
identidade é um número de telefone não carrega alçada administrativa.

**A colisão falha fechada.** Um telefone que fosse contato de cliente *e*
usuário do portal receberia capacidades de representante por um cadastro
descuidado — a rota de escalação mais barata deste desenho. Ela é impedida nas
duas bordas de escrita e recusada de novo em tempo de resolução.

O `404` não deveria ocorrer: o roster é espelhado pelo Gateway, que só encaminha
quem está nele. Se ocorrer, é sinal de roster defasado.

## Modelo de dados

### Papel

Nenhuma tabela de papéis nova. O papel no canal é derivado de `users.role`
(ADR-013) e da existência do contato em `customer_contacts`.

### Telefone

```
users
  whatsapp_e164   -- normalizado pelo módulo canônico
                  -- UNIQUE parcial (tenant_id, whatsapp_e164) WHERE NOT NULL
```

Hoje o campo passa apenas por validação de formato em `schemas/users.py`:
`+551188887777` é aceito e nunca casa com o `+5511988887777` que chega da Meta.
O módulo canônico sai de `services/customers.py` para `core/phone.py` — ele já
é único, o nome é que passa a mentir quando usuários também o usam.

**Não há tabela-registro de telefones.** Ela daria unicidade entre tabelas no
próprio banco, que o índice parcial não alcança, mas duplicaria o telefone e
criaria deriva. A checagem cruzada fica nos dois serviços de escrita, com
`python -m crm_api.admin_cli check-whatsapp-identities` para provar a
invariante. Isso contraria o "o banco recusa, não apenas o serviço" do R2, e a
diferença é deliberada: ali o banco podia recusar barato, aqui não pode, e a
resposta honesta é serviço mais reconciliação verificável.

### Roster — decisão D5

**O roster não muda.** `/internal/authorized-contacts` continua devolvendo
somente contatos ativos de clientes ativos, com o teto de 10.000 e o `409`: a
lista vem inteira ou vem erro, nunca truncada nem paginada.

O telefone do representante é autorizado à mão no painel do Gateway, como
autorização de origem `MANUAL` — que a reconciliação preserva por invariante, e
cujo commit de origem cita exatamente este caso, "o telefone do representante,
um número de teste".

Isso separa duas responsabilidades que estavam misturadas na primeira versão
deste documento: **o Gateway decide se atende; o CRM decide o que a pessoa
pode fazer.** A resolução do ator não depende do roster — ela lê
`users.whatsapp_e164` — então o manifesto por ator funciona sem que um único
representante entre na lista automática.

Duas consequências aceitas, e a mitigação de cada uma:

**O número passa a ser digitado em dois lugares.** No painel do Gateway, para
autorizar; no cadastro do CRM, para ser reconhecido. Se divergirem, o robô
atende e o CRM não reconhece: o representante recebe o manifesto de cliente ou
nada, sem erro visível em lugar nenhum. Mitigação: a tela `/portal/whatsapp`
mostra quais usuários têm telefone cadastrado e quais não têm, e o
`check-whatsapp-identities` acusa a divergência antes de ela virar atendimento
errado.

**Desativar o representante no portal não tira o acesso dele ao canal.** A
autorização `MANUAL` sobrevive à desativação, e só sai quando alguém a exclui no
painel do Gateway — que, desde o commit `dbd2d75`, mostra a origem de cada
autorização justamente porque "a diferença muda o resultado da ação". Mitigação:
item de checklist de desligamento, não automação. Risco assumido explicitamente
em 2026-08-16.

Se um dia isso incomodar, o caminho de volta é curto: acrescentar os
representantes ativos à consulta do roster faz a autorização virar origem `APP`,
e aí desativar no portal passa a tirar do canal no ciclo seguinte.

### Carteira

Nada muda. `customers.owner_user_id`, `customer_assignment_history` e o
`PortfolioScope` aplicado no repositório já são o vínculo que a carteira
precisa. No WhatsApp o escopo é o mesmo: `owner_user_id = actor.user_id`.

### Histórico de conversa do representante — decisão D6

```
customer_interactions
  customer_id       -- passa a ser nulável
  actor_user_id     -- novo, nulo quando o evento é de cliente
  CHECK: exatamente um dos dois preenchido
```

`POST /internal/interactions` resolve o evento hoje pelo contato E.164 e
**recusa** o que não encontra cliente. No instante em que o Gateway passar a
atender um representante, cada mensagem dele viraria um evento recusado.

A conversa do representante vira histórico dele, e não da ficha de um cliente
qualquer. Atribuí-la ao cliente que ele consultou foi recusado por dois motivos:
mensagem genérica — "bom dia", "obrigado" — não teria a que se ligar e voltaria
a ser recusada; e ler conversa de representante dentro da ficha do cliente
misturaria dois assuntos que a tela apresenta como um só.

Consequência para a LGPD: passa a existir conteúdo de conversa ligado a um
usuário identificado, não só a um contato de cliente. A Q3 — prazo de retenção,
ainda sem resposta — passa a valer para os dois.

### Pré-cadastro

```
customer_intakes
  id, tenant_id
  created_by_user_id        -- o representante, resolvido pelo ator
  source                    -- 'WHATSAPP'
  idempotency_key           -- wamid; UNIQUE(tenant_id, idempotency_key)
  legal_name, state_code
  whatsapp_e164             -- canônico, opcional
  preferred_products_text   -- texto livre, NÃO resolvido
  status                    -- PENDING | ACCEPTED | REJECTED
  customer_id               -- preenchido na aceitação
  rejected_reason
  created_at, resolved_at, resolved_by_user_id
```

Tabela separada, e não `customers` com marca de rascunho, pelo motivo do
ADR-020: o rascunho mora onde o consumidor de produção não lê. Um `customers`
inativo entraria em várias consultas que filtram por `active` e passaria a
significar duas coisas — "desativado" e "ainda não existe".

Três consequências desenhadas de propósito:

**Intake pendente não toca o roster.** Não existe `customer_contacts` até alguém
aceitar no portal. Criar um cliente com contato de WhatsApp é criar acesso ao
canal: o contato entra no roster, o Gateway espelha e passa a atender aquele
número. Se a mensagem gravasse o contato direto, uma frase no WhatsApp
autorizaria um telefone qualquer a conversar com o CRM.

**`preferred_products_text` é texto do representante, não SKU.** A LLM extrai a
frase literal e para aí. Casar "75/36 urdume" com um artigo é decisão comercial;
o ADR-021 já registra o que custa amarrar histórico de preço ao artigo errado. A
resolução acontece no portal, pelo combobox de artigo que já existe.

**A UF é obrigatória no intake.** Sem ela não há regra de ICMS, e o R4 falha de
propósito em vez de estimar. Pedir a UF na conversa custa menos que descobrir a
falta na hora de gerar a lista.

## Telas

| Tela | Quem | O que muda |
|---|---|---|
| `/portal/users` | `ADMIN` | WhatsApp normalizado e checado contra contatos de cliente; erro em português na colisão. Indicador "atende por WhatsApp". |
| `/portal/intake` (nova) | representante vê os seus; `ADMIN` e `MANAGER`, todos | Fila de pré-cadastros. Aceitar abre o formulário de cliente pré-preenchido; rejeitar exige motivo. Auditado. |
| Ficha do cliente | conforme carteira | Preferência vinda de intake aparece como texto do representante até ser resolvida — mesma escolha do "sem preço no mês" do ADR-020. |
| `/portal/whatsapp` (nova) | `ADMIN` | Roster vigente, contagem, `etag`, colisões, e **quais usuários têm telefone cadastrado** — a divergência com o painel do Gateway aparece aqui. Hoje o roster não tem visibilidade nenhuma: o Gateway espelha em silêncio e ninguém no CRM sabe o quê. |
| `/portal/whatsapp/nao-entendidas` (nova) | `ADMIN` | Mensagens que o robô não classificou. O dado **já chega hoje**: o Gateway empurra `intent_id: "UNKNOWN"` e `outcome: "FALLBACK"` no `payload` da interação, e o CRM já o persiste. Falta só a leitura. |
| `/portal/whatsapp/vocabulario` (nova) | `ADMIN` | Palavras e exemplos de cada capacidade, editáveis. Entram no manifesto seguinte, em no máximo 15 minutos. |

### Vocabulário no banco, não no código — decisão D7

Hoje aliases e exemplos são literais em `services/interaction_capabilities.py`:
acrescentar uma palavra é alterar arquivo, testar e publicar. A decisão de
ajustar o vocabulário conforme o uso torna isso inviável — vira uma tarefa de
programador por palavra.

As duas telas entram nesta ordem, e a ordem importa: sem o relatório do que não
foi entendido, escolher a próxima palavra é chute. Com ele, cada palavra nova
tem uma mensagem real por trás.

### Permissões

| Ação | ADMIN | MANAGER | REPRESENTATIVE |
|---|:-:|:-:|:-:|
| Criar, editar e desativar usuário | sim | não | não |
| Definir WhatsApp de usuário | sim | não | não |
| Designar e transferir titular | sim | sim | não |
| Aceitar intake | sim | sim | só os seus |
| Rejeitar intake | sim | sim | só os seus |
| Ver roster | sim | não | não |

Aceitar o próprio intake não é privilégio novo: o R2 já permite que um
`REPRESENTATIVE` crie cliente pelo portal e vire titular dele. O intake apenas
antecipa o preenchimento.

## Contrato

```
POST /api/integrations/whatsapp/v1/capabilities/manifest
X-Tenant-Slug, X-Timestamp, X-Signature
```

A assinatura permanece a do resto do limite interno: HMAC-SHA256 do valor UTF-8
`timestamp.method.path.body`, separado por ponto. Diferente das rotas atuais,
aqui o corpo não é vazio.

```json
{
  "contact_phone_e164": "+5511999999999",
  "channel_context": { "channel": "whatsapp", "line_phone_number_id": "1234567890" }
}
```

`actor.id` é opaco por exigência do v1, e o validador fixa o formato em 24
caracteres hexadecimais.

Ele é **sorteado e guardado**, não derivado: uma coluna `public_ref` em `users`
e em `customer_contacts`, com 12 bytes aleatórios em hexadecimal, única por
tenant. A alternativa — HMAC do UUID com um segredo — dispensaria a coluna, mas
amarraria a identidade do ator à rotação do segredo: girar a chave mudaria todos
os `actor.id` de uma vez, invalidando o cache do Gateway e fragmentando as
observações sanitizadas que ele persiste por contexto (`GW-081b`). Um
identificador estável não deve depender de um segredo que existe para ser
trocado.

Consequência boa: nenhum segredo novo em produção.

### Resposta ao representante

```json
{
  "schema_version": "business-capability-manifest/v1",
  "provider": "crm_api",
  "actor": { "id": "9f2c7d1e4b8a03f5", "role": "representante" },
  "channel_context": { "channel": "whatsapp", "line_phone_number_id": "1234567890" },
  "expires_in_seconds": 300,
  "capabilities": [
    {
      "id": "CRM_REP_SEARCH_PRICE_ITEMS",
      "action": "CRM_REP_SEARCH_PRICE_ITEMS",
      "mode": "read",
      "requires_confirmation": false,
      "idempotency": "none",
      "title": "Consultar artigo",
      "description": "Pesquisa artigo na tabela vigente em preço-base, sem conversão de ICMS.",
      "vocabulary": {
        "aliases": ["preço de", "quanto está"],
        "examples": ["75/36", "quando chega o 100/36?"]
      },
      "slots": [{ "id": "product_query", "required": true }]
    },
    {
      "id": "CRM_REP_LOOKUP_CUSTOMER",
      "action": "CRM_REP_LOOKUP_CUSTOMER",
      "mode": "read",
      "requires_confirmation": false,
      "idempotency": "none",
      "title": "Localizar cliente da carteira",
      "description": "Localiza cliente da carteira do representante por razão social, nome fantasia ou documento.",
      "vocabulary": {
        "aliases": ["cliente", "ficha do"],
        "examples": ["dados da Malhas Silva"]
      },
      "slots": [{ "id": "customer_query", "required": true }]
    },
    {
      "id": "CRM_REP_GET_CUSTOMER_PRICE_LIST",
      "action": "CRM_REP_GET_CUSTOMER_PRICE_LIST",
      "mode": "read",
      "requires_confirmation": false,
      "idempotency": "none",
      "title": "Tabela de um cliente",
      "description": "Tabela vigente de um cliente da carteira, convertida para a UF de entrega dele.",
      "vocabulary": {
        "aliases": ["tabela do", "lista do"],
        "examples": ["tabela da Malhas Silva"]
      },
      "slots": [{ "id": "customer_query", "required": true }]
    },
    {
      "id": "CRM_REP_CREATE_CUSTOMER_INTAKE",
      "action": "CRM_REP_CREATE_CUSTOMER_INTAKE",
      "mode": "write",
      "requires_confirmation": true,
      "idempotency": "required",
      "title": "Pré-cadastrar cliente",
      "description": "Abre pré-cadastro de cliente para conferência no portal. Não ativa o cliente nem autoriza o telefone dele no WhatsApp.",
      "vocabulary": {
        "aliases": ["cadastrar cliente", "novo cliente"],
        "examples": ["cadastrar cliente Malhas Silva, SP, gosta de 75/36 urdume"]
      },
      "slots": [
        { "id": "customer_legal_name", "required": true },
        { "id": "customer_state_code", "required": true },
        { "id": "customer_whatsapp", "required": false },
        { "id": "preferred_products_text", "required": false }
      ]
    }
  ],
  "help_message": "Posso consultar artigo, localizar cliente da sua carteira, enviar a tabela de um cliente e abrir pré-cadastro de cliente novo."
}
```

### Resposta ao cliente

```json
{
  "schema_version": "business-capability-manifest/v1",
  "provider": "crm_api",
  "actor": { "id": "3a81ff0c5d269e47", "role": "cliente" },
  "channel_context": { "channel": "whatsapp", "line_phone_number_id": "1234567890" },
  "expires_in_seconds": 900,
  "capabilities": [
    {
      "id": "GET_CURRENT_PRICE_LIST",
      "action": "GET_CURRENT_PRICE_LIST",
      "mode": "read",
      "requires_confirmation": false,
      "idempotency": "none",
      "title": "Tabela de preços",
      "description": "Envia a tabela de preços vigente do contato.",
      "vocabulary": {
        "aliases": ["tabela", "lista", "lista de preços", "valores atuais"],
        "examples": ["me envie a tabela de valores"]
      },
      "slots": []
    },
    {
      "id": "SEARCH_CURRENT_PRICE_LIST_ITEMS",
      "action": "SEARCH_CURRENT_PRICE_LIST_ITEMS",
      "mode": "read",
      "requires_confirmation": false,
      "idempotency": "none",
      "title": "Consultar artigo",
      "description": "Consulta artigo, preço, disponibilidade ou previsão de chegada na tabela vigente.",
      "vocabulary": {
        "aliases": ["preço do", "tem"],
        "examples": ["75/36", "quando chega o 100/36?"]
      },
      "slots": [{ "id": "product_query", "required": true }]
    }
  ],
  "help_message": "Posso enviar a tabela atual ou consultar um artigo. Exemplos: “lista de preços” ou “75/36 urdume”."
}
```

### Três leituras desse par

**O cliente mantém os dois `action` de hoje, sem prefixo.** Os executores já
existem no Gateway e não mudam. Os identificadores novos usam o prefixo `CRM_`,
como o CKJ usa `CKJ_`.

Sob o v1, `id` e `action` passam a ser a mesma string, porque o validador exige
`capability.id === capability.action`. Os identificadores de intenção atuais —
`LIST_CURRENT_PRICES` e `SEARCH_PRODUCT` — só sobrevivem no manifesto legado,
que continua servido pelo `GET` antigo e intocado.

**O representante não recebe `GET_CURRENT_PRICE_LIST`.** Não é escolha de
produto: os dois executores atuais chamam
`/price-lists/current/by-whatsapp/{phone}`, que resolve **cliente** por
telefone. Servidos a um representante, respondem "não encontrei uma tabela de
preços vigente para seu cadastro". As quatro capacidades de representante são
todas ações novas, e não há atalho.

**TTL menor para representante**, 300 contra 900 segundos. O teto do v1 é 900
para qualquer ator, bem abaixo dos 30 minutos que o ADR-012 fixou para o
manifesto legado; dentro desse teto, o representante recebe o menor prazo porque
carteira e permissões mudam e ele carrega uma capacidade de escrita.

### Ambiguidade sem estado conversacional

Quando `customer_query` casa com mais de um cliente, o CRM devolve até três
candidatos e o executor pede refinamento. Assim as capacidades de leitura não
dependem do `GW-023`, que está aberto.

## Mudanças no Gateway

Em ordem de dependência. As três primeiras são bloqueantes.

1. **Estender o v1 com `vocabulary` e `slots` por capacidade.** Sem isso, migrar
   o CRM apaga a resolução determinística e contraria o ADR-012. Atualiza o
   `GW-002`, a fixture compartilhada e o validador do `GW-011`.
2. **Criar o adaptador `crm_api` do endpoint canônico**, autenticado pelo HMAC
   atual, com `CRM_CAPABILITY_MANIFEST_ENABLED=false` por padrão, no formato das
   flags do CKJ. Fecha `GW-010` e `GW-015`.
3. **Enviar `contact_phone_e164` e `channel_context` na requisição.**
   `processCrmApiMessage` já tem o telefone e já o usa como chave de cache; ele
   só não viaja. É a mudança mais barata da lista.
4. **Registrar quatro executores novos:** `CRM_REP_SEARCH_PRICE_ITEMS`,
   `CRM_REP_LOOKUP_CUSTOMER`, `CRM_REP_GET_CUSTOMER_PRICE_LIST` e
   `CRM_REP_CREATE_CUSTOMER_INTAKE`. Sem eles a allowlist recusa o manifesto de
   representante inteiro, e corretamente.
5. **Incluir `actor.id` e `actor.role` na chave de cache** e invalidar na troca
   de ator — `GW-012` e `GW-013`, abertos.
6. **Implementar a máquina de confirmação**, `GW-040` a `GW-045`, abertos.
   Bloqueante apenas para o pré-cadastro; as três leituras entram antes.
7. **Nada no roster.** O consumidor já existe — commit `309f03b`, módulo
   `modules/contact_authorization_sync.js` — com as guardas de `count`, `etag`,
   lista vazia e encolhimento acima de 20% sobre um piso de 5 desativações. Pela
   D5 o representante nem passa por ele: é autorização `MANUAL` digitada no
   painel.
8. **Regressão do manifesto legado**, `GW-068`: o
   `GET /internal/interaction-capabilities` continua servindo o manifesto de
   cliente, intacto, até a flag virar. Nenhuma janela em que produção depende
   dos dois.

## Duas ordens que não podem inverter

**A interação de representante antes de o Gateway atendê-lo.** No instante em
que o primeiro número de representante for autorizado no painel do Gateway, ele
começa a empurrar as mensagens desse número, e `POST /internal/interactions`
hoje **recusa o evento**: resolve cliente por telefone e não encontra. O
`actor_user_id` da D6 precisa existir antes — inclusive para o piloto de um
número só.

**A canonização de `users.whatsapp_e164` antes de ele virar fonte de roster.**
Um telefone sem o nono dígito entraria na lista espelhada e nunca casaria com o
que chega da Meta.
