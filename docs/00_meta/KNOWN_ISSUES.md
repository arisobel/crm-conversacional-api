# Problemas conhecidos

Registre aqui somente problemas observados no código, testes, contratos ou comportamento do produto.

## Abertos

- A migração PostgreSQL ainda não foi executada em uma instância real.
- O contrato OpenAPI ainda não foi validado por ferramenta automatizada.
- A stack executável da API ainda não foi escolhida.
- O repositório está público; não devem ser adicionados segredos ou dados comerciais reais.
- O DDL torna `whatsapp_e164` único apenas por tenant, mas `GET /customers/by-whatsapp/{phone}` não define como identificar o tenant solicitante; uma consulta global poderia devolver dados de outro tenant.
- O OpenAPI declara HMAC como segurança global, porém o contrato não define como a identidade autenticada é associada a um tenant nem a F0 define sua implementação.
- O corte vertical solicitado inclui `GET /ready`, mas esse endpoint ainda não está descrito no OpenAPI.

## Resolvidos

- A documentação de orquestração continha referências indevidas ao projeto `pwa-fair`; corrigida na reorganização documental de 2026-07-28.
