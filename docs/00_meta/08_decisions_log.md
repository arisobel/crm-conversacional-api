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
