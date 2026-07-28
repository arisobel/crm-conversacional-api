# Backlog do MVP

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
- [ ] Persistência da fotografia imutável da oferta.
- [ ] Geração determinística da mensagem-base.
- [ ] Confirmação humana antes do envio.
- [ ] Envio via WhatsApp Gateway.
- [ ] Registro de status de saída.

## Fora do primeiro MVP

- Leitura automática de PDF em produção.
- Negociação totalmente autônoma.
- Exceções comerciais criadas pela LLM.
- Motor tributário generalista.
- Envio sem aprovação humana.
