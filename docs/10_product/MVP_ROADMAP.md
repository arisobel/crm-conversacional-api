# Roadmap do MVP

## Objetivo

Dar ao representante comercial uma ferramenta para atender sua carteira:
listas de preço por competência, personalizadas pelos produtos preferidos do
cliente e pelo ICMS da localidade onde ele recebe, com histórico de interações
e trilha de auditoria.

A direção completa está em [CRM de representantes](REPRESENTATIVE_DIRECTION.md).
O WhatsApp permanece como canal, não como interface primária.

## Fases concluídas

### F0 — Fundação

Documentação, DDL, OpenAPI, stack executável, PostgreSQL e saúde do serviço.

### F1 — Cadastros e tabela vigente no WhatsApp

Clientes, contatos, famílias, produtos e preferências por cliente. Leitura da
tabela `ACTIVE` por contato WhatsApp e comando `tabela` publicado no Gateway.

## Fases ativas

O detalhamento está em [F5 — Portal do representante](../40_delivery/F5_REPRESENTATIVE_PORTAL.md).

| Etapa | Entrega | Migração |
|---|---|---|
| R0 | Identidade, papéis, sessão e auditoria | `0003` |
| R1 | Representante e carteira de clientes | `0004` |
| R2 | Localidades do cliente | `0005` |
| R3 | Preço por competência, revisão e publicação | `0006` |
| R4 | Motor de ICMS por par de UF | `0007` |
| R5 | Histórico de interações | `0008` |
| R6 | Portal do representante | — |

R4 está bloqueada até a confirmação contábil da fórmula de conversão entre UFs.

## Fases despriorizadas

| Fase | Situação |
|---|---|
| F2 — Preços e condições | Reescrita como R3 e R4 |
| F3 — Oferta | Volta depois do portal |
| F4 — Gateway | Reduzida à ingestão de interações em R5 |

## Pós-portal — Campanhas de WhatsApp

Esta frente é planejada, não concluída. Seu desenho está em
[Campanhas de WhatsApp](WHATSAPP_CAMPAIGNS.md) e o backlog rastreável em
[D — Campanhas de WhatsApp](../00_meta/09_backlog.md).

| Etapa | Entrega | Dependências |
|---|---|---|
| C0 | Decisões de negócio, retenção e contrato CRM ↔ Gateway | Consentimento, alçadas, templates e limite de revisão nominal |
| C1 | Público determinístico, rascunho, snapshots e auditoria no CRM | C0; filtro por grupo/composição e atributos ainda não modelados |
| C2 | Executor operacional no Gateway | C0; templates Meta, consentimento, fila, rate limit e eventos |
| C3 | Projeção de resultados e portal de campanhas | C1 e C2; ligação com ficha/timeline do cliente |
| C4 | Capacidades conversacionais | C1–C3; allowlist e executor validados no Gateway |

O corte não altera a regra central do produto: representante só seleciona sua
carteira; `ADMIN` e `MANAGER` acompanham o tenant. O Gateway continua dono do
canal, do consentimento e do envio, e o CRM mantém a projeção comercial.

## Critérios globais

- Eventos e importações repetidos não duplicam processamento.
- Nenhum preço é produzido pela LLM.
- Valores monetários são decimais, nunca `float`.
- Uma competência mensal não exige nova tabela física.
- Um único preço vigente por produto por competência.
- Toda alteração de preço, titular ou cadastro é auditável.
- Um representante nunca lê dados de carteira alheia.

## Pós-MVP

Importação automática de PDFs, oferta e negociação, frete determinístico,
motor tributário completo (ST, DIFAL, Simples), múltiplas UFs de origem por
tenant e servidor MCP. Campanhas de WhatsApp são a frente pós-portal detalhada
acima; só avançam após as dependências C0.

## Evolução multiempresa

Congelada pelo ADR-013. O [backlog de representante multiempresa](MULTI_COMPANY_BACKLOG.md)
permanece como referência histórica; "representante" neste produto significa
usuário com carteira, não organização que representa várias empresas.
