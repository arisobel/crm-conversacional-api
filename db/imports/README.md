# Importação revisada de tabela de preços

O PDF em `docs/90_references` é evidência comercial, não uma fonte automática de dados
publicáveis. Converta e confira os itens em CSV usando o cabeçalho do arquivo de exemplo.

Crie inicialmente uma tabela em revisão:

```powershell
uv run python -m crm_api.imports.price_table `
  --file db/imports/tabela_especial_2026-07-20.csv `
  --name "Tabela especial" `
  --reference-month 2026-07-01 `
  --valid-from 2026-07-20T00:00:00-03:00
```

O comando acima cria uma lista `DRAFT`; ela não é retornada ao Gateway. Após revisar
produtos, preço, disponibilidade e datas, ative a mesma lista pelo UUID retornado:

```powershell
uv run python -m crm_api.imports.price_table --activate-price-list UUID_DA_TABELA
```

O ativador rejeita sobreposição com outra tabela `ACTIVE`. Não há sobrescrita: para
corrigir uma carga, crie uma nova lista com outra competência/nome após a conferência.

Para `OUT_OF_STOCK`, `SUSPENDED` e `CONSULT`, `base_price` pode ficar vazio. O importador
armazena zero técnico apenas porque o DDL exige valor não nulo; o endpoint devolve
`base_price: null` e o Gateway nunca deve exibir esse zero como preço.
