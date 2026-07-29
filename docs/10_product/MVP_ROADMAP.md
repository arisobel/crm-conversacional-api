# Roadmap do MVP

## Objetivo

Gerar e registrar ofertas comerciais personalizadas via WhatsApp a partir de produtos preferenciais, tabela vigente e regras auditáveis.

## F0 — Fundação

Documentação, DDL, OpenAPI, stack executável, PostgreSQL e saúde do serviço.

## F1 — Cadastros

Clientes, contatos, famílias, produtos e preferências por cliente.

**Corte entregue:** leitura da tabela ativa por contato WhatsApp e comando `tabela` no
Gateway. A próxima entrega deste corte é `produto <termo>`, para reduzir a tabela ativa a
itens encontrados deterministicamente.

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

## Operação administrativa

O painel administrativo interno inicia após a consulta específica de produto. Ele não é
um atalho para o banco: autentica usuários, chama a API do CRM e preserva trilha de
auditoria para cadastros e ativações de tabela.
