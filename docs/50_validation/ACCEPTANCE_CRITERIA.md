# Critérios de validação

## Banco

- Migração aplica em PostgreSQL limpo e transacionalmente.
- FKs e restrições rejeitam referências e valores inválidos.
- Índices atendem telefone, vigência, cliente e evento externo.

## API

- OpenAPI é válido.
- Dinheiro trafega como string decimal.
- Chave idempotente repetida conserva o resultado lógico.
- Prévia não cria oferta.
- Envio sem aprovação retorna conflito.
- Assinatura inválida é rejeitada.

## Cenário Vitória

Com cliente em SP e “75/36 trama cru” a 12,05, a API apresenta o preço-base, aplica a condição antecipada configurada, apresenta frete de 0,20/kg e preserva esses valores no snapshot mesmo após mudança da tabela.
