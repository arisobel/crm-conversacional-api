# Backlog priorizado

## P0 — Decisão multiempresa

- [ ] Aprovar [ADR e backlog de representante multiempresa](../10_product/MULTI_COMPANY_BACKLOG.md).
- [ ] Definir o significado definitivo de `tenant` e os limites de isolamento.
- [ ] Definir como linha e fluxo do Gateway resolvem a empresa representada.

## P0 — Fundação

- [ ] Definir stack e versão do runtime.
- [ ] Criar configuração local e para CapRover.
- [ ] Aplicar migrações PostgreSQL.
- [ ] Implementar autenticação interna por HMAC.
- [ ] Implementar idempotência por `event_id`.
- [ ] Criar testes de integração com PostgreSQL.

## P1 — Catálogo e preços

- [ ] CRUD de clientes e contatos.
- [ ] CRUD de famílias e produtos.
- [ ] Lista preferencial cliente-produto.
- [ ] Importação manual de tabela mensal.
- [ ] Consulta da tabela vigente.
- [ ] Regras determinísticas de desconto, frete e imposto.

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
