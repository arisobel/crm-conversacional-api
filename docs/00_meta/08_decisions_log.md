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
