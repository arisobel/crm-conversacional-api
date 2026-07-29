# Problemas conhecidos

Registre aqui somente problemas observados no código, testes, contratos ou comportamento do produto.

## Abertos

- A migração PostgreSQL ainda não foi executada em uma instância real.
- O contrato OpenAPI ainda não foi validado por ferramenta automatizada.
- O repositório está público; não devem ser adicionados segredos ou dados comerciais reais.

## Resolvidos

- A documentação de orquestração continha referências indevidas ao projeto `pwa-fair`; corrigida na reorganização documental de 2026-07-28.
- A busca por WhatsApp não tinha escopo de tenant; corrigida no corte F0 por `X-Tenant-Slug` autenticado via HMAC (ADR-008).
- O OpenAPI não descrevia `GET /ready`; corrigido no corte F0.
