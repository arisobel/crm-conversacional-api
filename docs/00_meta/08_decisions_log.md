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
