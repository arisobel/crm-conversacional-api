# Backlog priorizado

## P0 — Decisão multiempresa

- [ ] Aprovar [ADR e backlog de representante multiempresa](../10_product/MULTI_COMPANY_BACKLOG.md).
- [ ] Definir o significado definitivo de `tenant` e os limites de isolamento.
- [ ] Definir como linha e fluxo do Gateway resolvem a empresa representada.

## P0 — Fundação

- [x] Definir stack e versão do runtime.
- [x] Criar configuração local e para CapRover.
- [x] Aplicar migrações PostgreSQL no ambiente CapRover.
- [x] Implementar autenticação interna por HMAC.
- [ ] Implementar idempotência por `event_id`.
- [ ] Criar testes de integração com PostgreSQL.

## P1 — Catálogo e preços

- [ ] CRUD de clientes e contatos.
- [ ] CRUD de famílias e produtos.
- [ ] Lista preferencial cliente-produto.
- [x] Executar, revisar e ativar a importação manual da tabela especial de 20/07/2026.
- [x] Implementar a consulta interna da tabela vigente por contato WhatsApp.
- [x] Adicionar ordenação explícita de item de tabela (`0002`) para preservar a sequência comercial revisada.
- [x] Integrar o comando `tabela` no Gateway compartilhado.
- [ ] Consulta específica de item por SKU, nome comercial, especificação ou família.
- [ ] Validar em produção o manifesto de capacidades por sessão no `crm_api`.
- [ ] Migrar aliases e intenções CRM para configuração administrativa auditável.
- [ ] Regras determinísticas de desconto, frete e imposto.

## P2 — Operação administrativa

- [ ] Fase A: definir autenticação, papéis e auditoria do painel interno.
- [ ] Fase B: CRUD administrativo de clientes e contatos, incluindo estado de autorização Gateway.
- [ ] Fase C: CRUD de famílias, produtos e preferências por cliente.
- [ ] Fase D: importação CSV com prévia, validação, revisão e ativação auditável.
- [ ] Fase E: aliases, exemplos e versão do manifesto conversacional CRM.
- [ ] Integração CRM → Gateway para solicitar autorização de telefone de forma idempotente.

## P1 — Oferta

- [ ] Prévia de oferta.
- [ ] Fotografia imutável da oferta.
- [ ] Geração da mensagem-base.
- [ ] Confirmação humana.
- [ ] Envio via Gateway.
- [ ] Registro de status de entrega.

## Fora do primeiro MVP

- Leitura automática de PDF em produção.
- Negociação totalmente autônoma.
- Exceções comerciais criadas pela LLM.
- Motor tributário generalista.
- Envio sem aprovação humana.
