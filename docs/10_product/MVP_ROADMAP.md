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
tenant e servidor MCP.

## Evolução multiempresa

Congelada pelo ADR-013. O [backlog de representante multiempresa](MULTI_COMPANY_BACKLOG.md)
permanece como referência histórica; "representante" neste produto significa
usuário com carteira, não organização que representa várias empresas.
