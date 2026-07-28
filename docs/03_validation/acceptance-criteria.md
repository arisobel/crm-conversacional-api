# Critérios de validação

## Banco

- A migração aplica em PostgreSQL limpo e dentro de transação.
- Chaves estrangeiras impedem referências inválidas.
- Restrições rejeitam valores monetários negativos e períodos incoerentes.
- Índices atendem buscas por telefone, vigência, cliente e evento externo.

## API

- O contrato OpenAPI é válido.
- Valores monetários trafegam como strings decimais.
- Um `Idempotency-Key` repetido retorna o mesmo resultado lógico.
- A prévia não cria uma oferta.
- O envio de oferta não aprovada retorna conflito.
- Eventos inválidos ou com assinatura incorreta são rejeitados.

## Cenário Vitória

Dada uma cliente em SP e o produto “75/36 trama cru” com preço-base 12,05:
- a API apresenta preço a prazo de 12,05;
- aplica a regra antecipada configurada;
- apresenta frete de 0,20 por kg;
- registra os valores usados ao criar a oferta;
- preserva a fotografia mesmo após alteração da tabela vigente.
