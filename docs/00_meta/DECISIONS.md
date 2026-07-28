# Registro de decisões

## ADR-001 — Separar Gateway e domínio comercial

**Status:** aceita.

O repositório `arisobel/whatsapp-webhook-caprover` permanece responsável pela integração técnica compartilhada com a Meta. Este repositório concentra catálogo, preços, clientes, ofertas, conversas e persistência.

## ADR-002 — PostgreSQL com competência em coluna

**Status:** aceita.

Usar tabelas estáveis com `reference_month`, `valid_from` e `valid_until`. Não criar tabelas mensais como `prices_202607`. Particionamento físico poderá ser introduzido sem alterar o modelo lógico.

## ADR-003 — Cálculo determinístico

**Status:** aceita.

A LLM interpreta intenção e redige linguagem comercial, mas não inventa preço nem consulta o banco diretamente. Preço, desconto, frete, imposto e disponibilidade são calculados por operações controladas da API.

## ADR-004 — Fotografia imutável da oferta

**Status:** aceita.

Ao criar uma oferta, cada item copia descrição, valores, regras e disponibilidade utilizados. Mudanças posteriores na tabela não alteram propostas históricas.

## ADR-005 — Confirmação humana

**Status:** aceita para o MVP.

Toda oferta exige aprovação humana antes do envio pelo Gateway.

## ADR-006 — API HTTP antes de MCP

**Status:** aceita.

O MVP consolida primeiro domínio e API HTTP. Um servidor MCP poderá expor posteriormente operações estáveis como `find_customer`, `calculate_offer` e `send_offer`.
