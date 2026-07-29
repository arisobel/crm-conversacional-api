# F0 — Fundação

## Objetivo

Transformar os artefatos atuais em um serviço mínimo executável.

## Entregáveis

- stack e runtime definidos;
- configuração local e CapRover;
- conexão PostgreSQL;
- migração `0001_initial.sql` aplicada;
- validação do OpenAPI;
- endpoint `GET /health`;
- endpoint `GET /ready`;
- busca de cliente por WhatsApp;
- testes automatizados básicos.

## Mecanismo de migração

`db/migrations/0001_initial.sql` continua sendo a referência conceitual aprovada do
schema inicial. `alembic/versions/0001_initial_schema.py` é o mecanismo executável: ele
aplica esse DDL dentro da transação controlada pelo Alembic. Não há um segundo schema
concorrente.

## Saída

F0 termina quando uma instalação limpa sobe, aplica o banco, responde saúde e executa os testes documentados.
