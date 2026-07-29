# Backlog priorizado

## P0 — Fundação

- [x] Definir stack e versão do runtime.
- [x] Criar configuração local e para CapRover.
- [ ] Aplicar migrações PostgreSQL.
- [x] Implementar autenticação interna por HMAC.
- [ ] Implementar idempotência por `event_id`.
- [ ] Criar testes de integração com PostgreSQL.

## P1 — Catálogo e preços

- [ ] CRUD de clientes e contatos.
- [ ] CRUD de famílias e produtos.
- [ ] Lista preferencial cliente-produto.
- [ ] Executar a importação manual revisada da tabela especial de 20/07/2026.
- [x] Implementar a consulta interna da tabela vigente por contato WhatsApp.
- [x] Adicionar ordenação explícita de item de tabela (`0002`) para preservar a sequência comercial revisada.
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
