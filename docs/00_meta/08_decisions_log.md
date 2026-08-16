# Registro de decisões

## ADR-001 — Separar Gateway e domínio comercial

**Status:** aceita.

`arisobel/whatsapp-webhook-caprover` permanece como gateway compartilhado da Meta. Este repositório concentra clientes, catálogo, preços, ofertas, conversas e persistência.

## ADR-002 — PostgreSQL com competência em coluna

**Status:** aceita.

Usar tabelas estáveis com `reference_month`, `valid_from` e `valid_until`; não criar tabelas físicas por `YYYYMM`.

## ADR-003 — Cálculo determinístico

**Status:** aceita.

A LLM interpreta intenção e redige, mas não inventa preços, executa SQL livre ou modifica regras comerciais.

## ADR-004 — Fotografia imutável da oferta

**Status:** aceita.

A oferta copia descrição, valores, regras e disponibilidade usados no cálculo, preservando o histórico.

## ADR-005 — Confirmação humana no MVP

**Status:** aceita.

Uma oferta só pode ser enviada depois de aprovação humana explícita.

## ADR-006 — API HTTP antes de MCP

**Status:** aceita.

O domínio e a API HTTP serão estabilizados antes de uma eventual camada MCP.

## ADR-007 — Documentação por função

**Status:** aceita em 2026-07-28.

A documentação passa a usar `00_meta`, `10_product`, `20_domain`, `30_architecture`, `40_delivery` e `50_validation`. DDL e OpenAPI permanecem como artefatos técnicos executáveis em diretórios próprios.

## ADR-008 — Tenant resolvido pelo Gateway em chamadas internas

**Status:** aceita em 2026-07-28.

O `whatsapp-webhook-caprover` já resolve linha Meta, aplicativo e fluxo no plano de
controle. Nas chamadas síncronas para esta API, ele informa `X-Tenant-Slug` e assina a
requisição com HMAC, timestamp e corpo canônicos. Cada implantação do CRM aceita somente
o tenant configurado. A decisão preserva a unicidade de telefone por tenant no DDL e
impede busca acidental de um contato em outro tenant.

## ADR-009 — Importação comercial revisável antes da ativação

**Status:** aceita em 2026-07-29.

A tabela especial recebida em PDF é uma referência comercial de duas colunas, com linhas
de preço, disponibilidade e chegada que não podem ser publicadas por extração automática
sem revisão. O CRM aceitará carga manual estruturada em CSV, gerará a tabela inicialmente
como `DRAFT` e exigirá ativação explícita. Itens sem preço atual são representados por
disponibilidade controlada e não são expostos como preço zero ao Gateway.

## ADR-010 — Comando explícito para consulta de tabela no WhatsApp

**Status:** aceita em 2026-07-29.

O Gateway interpreta somente `tabela`, `tabela de preço` e `tabela de preços` como
pedido da lista completa. Ele chama o CRM pela rede interna do CapRover com o mesmo HMAC e
tenant do lookup de cadastro. O CRM continua sendo a única fonte de preço e
disponibilidade; o Gateway apenas formata a resposta. A lista enviada informa valores-base
por kg, nunca simula condição de pagamento, frete, imposto ou desconto ainda não
configurados.

## ADR-011 — Interface administrativa como cliente da API, não do banco

**Status:** aceita em 2026-07-29.

O futuro painel administrativo será uma aplicação interna autenticada que usa operações
administrativas próprias do CRM. Não receberá URL, usuário ou senha do PostgreSQL e não
alterará tabelas diretamente. O MVP do painel cobre clientes/contatos, famílias/produtos,
importação revisável de CSV, revisão de itens e ativação auditável de tabela.

## ADR-012 — Manifesto de capacidades por backend durante a sessão

**Status:** aceita em 2026-07-29.

O Gateway permanece responsável por receber, rotear, interpretar mensagens livres e
responder no canal. Cada backend pode publicar, por um endpoint interno autenticado, um
manifesto versionado de intenções, aliases, exemplos, slots necessários e ações permitidas.
Na primeira mensagem da sessão `linha + fluxo + contato`, o Gateway carrega o manifesto do
backend selecionado e o mantém em cache por inatividade; para o CRM, o TTL inicial é de
30 minutos. Uma nova sessão recarrega a versão vigente.

O manifesto não pode conter URL arbitrária, SQL, fórmula comercial, segredo, código ou
prompt executável. Ações são identificadores fechados que o adaptador local do Gateway
conhece e autoriza. A classificação usa regras do manifesto primeiro e LLM estruturada
somente como fallback; a LLM pode retornar uma intenção e slots, mas nunca preço, cálculo
ou resposta comercial inventada.

O piloto aplica-se exclusivamente ao `crm_api`. CKJ e Liondata permanecem nos adaptadores
atuais até que o mecanismo seja validado em produção.

## ADR-013 — Representante é usuário com carteira, não organização

**Status:** aceita em 2026-08-04.

O produto passa a ser um CRM operado por representantes comerciais. Um
representante é um **usuário autenticado dentro de um tenant**, com papel
`REPRESENTATIVE` e uma carteira de clientes; ele não é uma organização que
representa várias empresas fornecedoras.

O titular vigente fica denormalizado em `customers.owner_user_id` e o histórico
de titularidade em `customer_assignment_history`. O escopo de leitura é aplicado
no repositório, não na apresentação.

Consequência: o [backlog de representante multiempresa](../10_product/MULTI_COMPANY_BACKLOG.md)
fica congelado e seus itens `MC-001` a `MC-007` saem do backlog priorizado. Se a
organização multiempresa voltar, ela será um eixo adicional de isolamento, não
um substituto deste.

## ADR-014 — Competência e produto como chave do preço vigente

**Status:** aceita em 2026-08-04.

A chave de idempotência comercial do preço é `(tenant, reference_month, product_id)`.
Existe **um único preço vigente por produto por competência**. Publicar a mesma
competência duas vezes é um `UPSERT`, nunca uma segunda tabela.

`price_entries` passa a ser a fonte de verdade e `price_entry_revisions` guarda
o histórico append-only de cada gravação. `price_lists` e `price_list_items` não
são removidas: passam a representar o lote de importação revisável exigido pelo
ADR-009, e a ativação do lote promove os valores para `price_entries`.

Consequência: a coexistência de "tabela normal" e "tabela especial" no mesmo mês
deixa de existir. A tabela especial de 20/07/2026 é modelada como uma **revisão
dentro da competência 2026-07**, com autor, momento e valor anterior. O ADR-002
permanece válido — a competência continua sendo coluna, não tabela física.

## ADR-015 — ICMS por matriz de UF de origem e destino

**Status:** aceita em 2026-08-04 quanto ao modelo; fórmula pendente.

O preço entregue ao cliente varia pela localidade onde ele recebe. A alíquota é
resolvida por `icms_rules`, com par `(origin_state, destination_state)`,
vigência e especialização opcional por produto, família e cliente. A UF de
origem vive em `tenants.origin_state_code`.

A precedência é determinística, da mais específica para a mais genérica:
cliente+produto, cliente+família, cliente, produto, família, par de UF puro.
Empate no mesmo nível resolve por `priority` e depois por `valid_from` mais
recente; se ainda houver empate, o serviço **falha explicitamente**. Ausência de
regra também falha: não existe alíquota-padrão implícita.

A `tax_rules` atual, pendurada em `price_list_id`, fica depreciada e deixa de
ser lida; sua remoção física exige ADR próprio.

**Pendente:** a fórmula de conversão entre UFs — cálculo "por dentro"
(gross-up) ou acréscimo simples — e se o preço-base carregado já contém ICMS
embutido. São decisões fiscais e precisam de confirmação contábil antes da
implementação. Elas alteram o serviço de cálculo, não o modelo de dados.

Fora de escopo no primeiro corte: substituição tributária, DIFAL, redução de
base e Simples Nacional.

## ADR-016 — Interações como projeção de leitura no CRM

**Status:** aceita em 2026-08-04.

O representante precisa ver, na ficha do cliente, o histórico de interações do
WhatsApp. O Gateway continua dono do canal, conforme o ADR-001; ele empurra para
o CRM, por endpoint interno HMAC e idempotente, uma projeção append-only em
`customer_interactions`, idempotente por `(source, external_ref)`.

O CRM não passa a operar o canal: ele guarda apenas o que a ficha precisa
exibir. O destino arquitetural de `conversations`, `messages`, `inbound_events` e
`outbound_messages` permanece o Gateway — `customer_interactions` é justamente o
que remove a necessidade de lê-las aqui.

Falha do push não pode degradar o atendimento no canal. A retenção é
configurável e o expurgo é auditado.

## ADR-017 — Portal server-rendered na mesma origem da API

**Status:** aceita em 2026-08-05. Resolve a questão Q4 e **revisa** a
recomendação registrada em `REPRESENTATIVE_DIRECTION.md`, que era de aplicação
separada.

A recomendação original foi escrita antes da sessão existir. Com o desenho que
R0 produziu — cookie `httpOnly`, `SameSite=Lax`, estado no servidor — uma
interface em **outra origem** obriga a três concessões que só existem por causa
da origem: baixar o cookie para `SameSite=None`, habilitar CORS com credenciais
e acrescentar proteção anti-CSRF explícita. `SameSite=None` é precisamente a
configuração que reabre o vetor de CSRF que o `Lax` fechava de graça.

O portal passa a ser servido pelo próprio processo FastAPI, com Jinja2, sob o
prefixo `/portal`. Não há build de front-end nem segundo deploy: o mesmo
`build.ps1` e o mesmo contêiner entregam API e telas.

O ADR-011 permanece respeitado: ele proíbe a interface falar com o PostgreSQL,
não que ela seja servida pelo mesmo processo. As rotas do portal chamam os
mesmos serviços que a API expõe e não têm acesso privilegiado a nada.

Consequências aceitas:

- Interface menos dinâmica que uma SPA. As telas de cadastro são formulários;
  o custo aparece só se surgir necessidade de interação rica.
- API e portal escalam juntos, por serem o mesmo processo.
- A proteção CSRF é por double-submit cookie, que também cobre o formulário de
  login — onde ainda não existe sessão para o `SameSite=Lax` proteger.

Se um dia a interface precisar sair para outra origem, a saída existe: as rotas
`/admin/*` já são o contrato completo, e o portal é um cliente delas.

## ADR-018 — Expurgo de interações recusa rodar sem política de retenção

**Status:** aceita em 2026-08-06. Complementa o ADR-016.

`CRM_INTERACTION_RETENTION_DAYS` não tem valor padrão, e o expurgo levanta erro
quando é chamado sem ela. A alternativa óbvia — assumir 365 dias, ou 90 — foi
recusada: por quanto tempo conteúdo de conversa pode ficar guardado é decisão de
LGPD, e um número escolhido pelo código a tomaria em silêncio, com a aparência
de política.

O comportamento sem configuração é conservador na direção certa: **nada é
apagado**. Reter demais é um problema que se corrige rodando o expurgo depois;
apagar cedo demais não se corrige.

O comando aceita `--dry-run`, que executa a remoção dentro da transação e a
desfaz. O número relatado é o real, não uma estimativa — quem vai definir o
prazo consegue ver quanto cada corte removeria antes de escolher.

Consequência aceita: o histórico cresce sem limite até alguém decidir. A
projeção guarda resumo truncado em 2000 caracteres, não a conversa inteira, o
que mantém o crescimento em ordem de grandeza tratável.

## ADR-019 — Documentação interativa desligada por padrão

**Status:** aceita em 2026-08-06.

`/docs`, `/redoc` e `/openapi.json` passam a depender de `CRM_EXPOSE_API_DOCS`,
que vale `false`. Antes eles subiam sempre.

A superfície administrativa cresceu muito desde F0: publicação de preço, matriz
de ICMS, gestão de usuários, histórico de conversa. O esquema não é segredo — a
segurança não depende dele — mas publicá-lo entrega um mapa completo e navegável
a quem apenas alcança a URL, e o custo de deixá-lo ligado é zero benefício em
produção, onde ninguém explora a API pelo navegador.

O contrato continua versionado e legível em `openapi/crm-api.yaml`, que é a
fonte de verdade para o Gateway de qualquer forma. Ligar em desenvolvimento é
uma variável de ambiente.

Junto com isso, todo resposta passa a carregar `Content-Security-Policy` com
`frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options` e
`Referrer-Policy: same-origin`. O portal não carrega script nem estilo de fora,
então a política pode ser restritiva sem quebrar nada — e o dia em que alguém
introduzir um CDN, a CSP vai avisar antes de o usuário descobrir.

## ADR-020 — Artigo cadastrado pela tela entra como rascunho, não como preço vigente

**Status:** aceita em 2026-08-10. Aplica o ADR-009 à ficha do cliente.

A ficha do cliente passa a cadastrar artigo que não existe no catálogo. O
produto entra em `products` na hora; o preço entra como `price_list_items` de um
lote `DRAFT` da competência corrente, e **só vale depois que alguém publicar o
lote** em `/portal/prices`.

Gravar direto em `price_entries` seria um clique a menos e foi recusado por dois
motivos concretos. O primeiro é alcance: `price_entries` é o que a rota consumida
pelo Gateway lê, então um preço digitado numa caixa de texto passaria a ser
servido no mesmo segundo, sem ninguém conferir. O segundo é rastreabilidade: a
revisão de preço guarda `source_batch_id`, e uma entrada sem lote de origem
deixaria a trilha do R3 com um buraco exatamente nas linhas criadas à mão.

O lote tem nome fixo — `Inclusões pelo portal` — que, com a competência, forma a
chave `(tenant, nome, competência)`. Assim o segundo artigo do mês cai no mesmo
lote: publicar cinquenta lotes de uma linha cada não é revisão, é ruído. Quando
o lote do mês já foi publicado, abre-se `Inclusões pelo portal (2)`, porque um
lote publicado que recebe item novo passa a mentir sobre o próprio estado.

Consequência aceita: entre cadastrar e publicar, o artigo é preferido do cliente
e **não aparece** na lista de preço dele — `list_items_for_products` só devolve o
que tem entrada na competência. Como a omissão é silenciosa por construção, a
ficha marca esses preferidos com "sem preço no mês" em vez de deixar o usuário
descobrir sozinho.

Criar artigo é privilégio de `ADMIN` e `MANAGER`, os mesmos papéis que já
transferem titular. O representante continua escolhendo entre o que existe.

## ADR-021 — O cadastro é dono do nome do artigo; a planilha do mês, do preço

**Status:** aceita em 2026-08-10. Revisa o comportamento de importação do F1 e
completa a Fase C do backlog administrativo.

`/portal/products` passa a manter o catálogo: criar, editar e desativar artigo,
e criar, renomear, reordenar e desativar família. Isso cria uma divisão que não
existia enquanto o CSV era o único caminho de entrada — e ela precisa ser
explícita, porque as duas fontes descrevem o mesmo artigo.

**O cadastro é dono de nome comercial e especificação.** O importador deixa de
abortar quando a planilha traz um nome diferente do gravado: ele mantém o do
cadastro e lista as divergências no fim da execução. O comportamento anterior
— `existing product conflicts with CSV` derrubando a importação inteira — só
fazia sentido quando ninguém podia editar pela tela; com a tela, ele passaria a
quebrar a carga mensal por causa de uma correção de redação. Sobrescrever com o
valor do CSV foi recusado por ser a única das três opções que perde trabalho em
silêncio.

**A família continua abortando.** Ela não é redação. Um SKU que muda de família
quase sempre é SKU reaproveitado para outro produto, e nesse caso todo o
histórico de preço passaria a pertencer ao artigo errado.

**O SKU trava no primeiro preço publicado.** Antes disso ele é editável, porque
corrigir um SKU recém-digitado é comum. Depois, não: o SKU é a coluna pela qual
a planilha reencontra o artigo, e trocá-lo faria a importação seguinte criar um
segundo artigo com o SKU antigo — o catálogo duplicaria sem ninguém ver. A tela
mostra o campo travado com o motivo, em vez de aceitar e falhar depois.

**Desativar artigo não desfaz preferência de cliente.** `Product.active` é
filtrado na tabela do mês e na lista do representante, então desativar tira o
artigo da circulação; a preferência fica guardada e volta inteira na reativação.
Como a consequência é invisível na ficha, ela passa a ser marcada lá — mesma
decisão que produziu o aviso de "sem preço no mês" no ADR-020.

Consequência aceita: nome comercial e especificação podem divergir entre o
cadastro e a planilha indefinidamente, e só quem lê a saída da importação fica
sabendo. A alternativa seria uma tela de conciliação, que não se justifica
enquanto uma pessoa carrega a tabela.

## ADR-022 — Manifesto por ator no envelope canônico do Gateway

**Status:** aceita em 2026-08-16. Revisa o ADR-012 e completa o ADR-013 no canal
WhatsApp. Desenho completo em
[WHATSAPP_ACTOR_MANIFEST.md](../30_architecture/WHATSAPP_ACTOR_MANIFEST.md).

Representante e cliente conversam pela mesma linha e o mesmo fluxo, e recebem
capacidades diferentes. A diferença vive no manifesto, nunca no roteamento: dois
fluxos com o mesmo telefone na mesma linha fazem o Gateway registrar
`CONTROL ROUTE AMBIGUOUS` e calar, em vez de escolher.

O CRM passa a publicar `POST /api/integrations/whatsapp/v1/capabilities/manifest`
no envelope `business-capability-manifest/v1`, que já carrega `actor { id, role }`.
A opção de evoluir `/internal/interaction-capabilities` foi recusada: seria
mexer num contrato de produção para criar um formato que só o CRM fala, e que o
`GW-015` do Gateway já prevê migrar de qualquer maneira.

**O TTL do manifesto cai de 30 para 15 minutos.** Não é escolha: o validador do
Gateway recusa `expires_in_seconds` acima de 900. O ADR-012 fixava 30 minutos;
esta é a parte dele que fica revogada. O efeito prático é o dobro de chamadas de
manifesto, irrelevante no volume atual.

**A migração é condicionada a estender o v1** com `vocabulary` e `slots` por
capacidade. Sem isso, o Gateway perde a resolução determinística: hoje ele lê
`intents[].aliases`, e o v1 mínimo não tem onde guardá-los. Adotar o envelope
literal entregaria toda a classificação à LLM, o oposto do que o ADR-012
estabelece.

**Quem o Gateway atende continua sendo decidido em dois lugares diferentes.** O
roster automático (`/internal/authorized-contacts`) permanece só de clientes; o
telefone do representante é autorizado à mão no painel do Gateway, como origem
`MANUAL`. Consequência aceita explicitamente: desativar o representante no
portal **não** tira o acesso dele ao canal, e o número passa a ser digitado em
dois sistemas. As mitigações são a tela `/portal/whatsapp` e o
`check-whatsapp-identities`, não automação.

**O papel nunca é decidido pela LLM.** Ela classifica intenção e extrai slots
declarados. `ADMIN` e `MANAGER` falando pelo WhatsApp recebem o manifesto de
representante: um canal cuja identidade é um número de telefone não carrega
alçada administrativa.

## ADR-023 — Apelido público sorteado, não derivado de segredo

**Status:** aceita em 2026-08-16.

O `actor.id` do manifesto é um `public_ref` sorteado e guardado em `users` e
`customer_contacts`, com 12 bytes em hexadecimal — o formato `^[a-f0-9]{24}$`
que o validador do Gateway impõe.

Derivá-lo por HMAC do UUID dispensaria as duas colunas, e foi recusado: um
segredo existe para ser rotacionado — o contrato interno já tem
`CRM_INTERNAL_HMAC_PREVIOUS_SECRET` para isso — e girar a chave mudaria todos os
identificadores de ator de uma vez, invalidando o cache do Gateway e partindo em
dois o histórico de observação que ele persiste por contexto. Identidade estável
não pode depender de um valor projetado para mudar.

Consequência: nenhum segredo novo entra em produção por causa do manifesto.

## ADR-024 — Vocabulário no banco, editável pelo portal

**Status:** aceita em 2026-08-16.

Aliases e exemplos das capacidades saem do código e passam a viver no banco,
editáveis por `ADMIN`, alimentados por um relatório das mensagens que o robô não
classificou.

O que motiva é operacional: com o vocabulário literal em
`services/interaction_capabilities.py`, acrescentar uma palavra é alterar
arquivo, testar e publicar o serviço — uma tarefa de programador por palavra,
incompatível com ajustar a compreensão conforme o uso.

O relatório vem primeiro, e a ordem é a decisão: sem ele, escolher a próxima
palavra é chute. O dado necessário **já chega hoje** — o Gateway empurra
`intent_id: "UNKNOWN"` e `outcome: "FALLBACK"` no `payload` da interação, e o
CRM já o persiste. Falta apenas a leitura.

## ADR-025 — Identificador de produto por tipo de slot, nunca por padrão transportado

**Status:** aceita em 2026-08-16. Complementa o ADR-022 e responde a uma lacuna
que só apareceu quando o Gateway implementou a extensão do envelope
(`e122bb6`).

`vocabulary` devolve ao CRM a lista de sinônimos, mas não o reconhecimento de
identificador: `75/36` é casado hoje por uma expressão regular escrita dentro do
Gateway, e nenhum campo de texto declarativo expressa isso.

Transportar a expressão no manifesto foi recusado, e a recusa é correta —
expressão regular de origem remota é ReDoS e superfície de injeção, e o contrato
já proíbe transportar código, template ou função.

Um slot passa a declarar `kind`, e o Gateway guarda localmente o casador de cada
tipo registrado. O CRM declara **qual** tipo, nunca o padrão; tipo desconhecido é
recusado como qualquer ação desconhecida.

Consequência aceita: a forma `NN/NN` do código têxtil continua morando no
Gateway, contra a letra do ADR-012. A diferença é de natureza, não de grau —
hoje é uma regex solta no meio de uma função, invisível a qualquer revisão; passa
a ser um tipo nomeado e registrado, que uma segunda aplicação reusa ou recusa
explicitamente.

Alternativa guardada para quando existir um segundo formato: descrição
declarativa de dígitos e separadores, compilada localmente com quantificadores
limitados — dados, não padrão. Não se justifica para um formato só.

## ADR-026 — O Gateway é dono do registro de tipos de slot

**Status:** aceita em 2026-08-16. Fecha a governança que o ADR-025 deixou aberta,
espelhando o DEC-046 do Gateway.

O enum de `kind` pertence ao **Gateway**, não ao CRM. O motivo é que a posse
segue o casador: um tipo sem casador local não significa nada, e o casador é
código que várias aplicações compartilham. É a assimetria em relação à allowlist
de ações — que é por aplicativo, porque ação pertence a quem a executa — e ela
parece descuido se ninguém escrever o porquê.

O CRM **pede** um tipo; não o declara unilateralmente. O preço é explícito: cada
tipo novo custa um deploy do Gateway mais a atualização coordenada do enum no
JSON Schema compartilhado, que um teste de contrato compara com o registro.

Daí a regra de uso, que é o que evita esse preço virar rotina: **`vocabulary`
primeiro, `kind` por exceção.** Alias e exemplo custam zero e, pelo ADR-024, são
editáveis no portal sem publicar nada. `kind` só se justifica para o que alias
nenhum expressa — identificador com estrutura, como `75/36`. Hoje existe um tipo
registrado, `product_code`, e não há um segundo à vista.

Três consequências herdadas do DEC-046:

- **`kind` é opcional.** A maioria dos slots deste desenho não declara nenhum.
- **`kind` ainda é inerte.** Quem vai lê-lo na resolução de intenção é o
  `GW-021`, que segue aberto. Declará-lo agora não muda comportamento nenhum, e
  o planejamento da W6 precisa contar com isso.
- **A regex têxtil foi extraída byte a byte**, não reescrita, e os testes do
  manifesto legado passaram sem alteração — que é a prova de que o caminho hoje
  em produção não mudou.

Para os próximos pedidos ao Gateway, isso vira critério de aceite permanente:
**comportamento do manifesto legado do CRM inalterado, provado pelos testes
existentes sem nenhuma modificação neles.** É o único jeito de uma alteração
dessas quebrar produção em silêncio.
