# Roadmap do MVP

## Objetivo

Gerar e registrar ofertas comerciais personalizadas via WhatsApp a partir de produtos preferenciais, tabela vigente e regras auditáveis.

## F0 — Fundação

Documentação, DDL, OpenAPI, stack executável, PostgreSQL e saúde do serviço.

## F1 — Cadastros

Clientes, contatos, famílias, produtos e preferências por cliente.

## F2 — Preços e condições

Tabela por competência/vigência, disponibilidade, chegada, pagamento, frete e impostos.

## F3 — Oferta

Prévia, fotografia imutável, aprovação humana e texto final.

## F4 — Gateway

Entrada idempotente, envio aprovado e atualização de status.

## Critérios globais

- Eventos repetidos não duplicam processamento.
- Nenhum preço é produzido pela LLM.
- Valores monetários são decimais.
- Uma tabela mensal não exige nova tabela física.
- Toda oferta enviada permanece auditável.

## Pós-MVP

Importação automática de PDFs, negociação autônoma, motor tributário genérico e servidor MCP.
