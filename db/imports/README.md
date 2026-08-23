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

# Importação de composição por fibra

Camada têxtil, migração `0014`. Diferente da tabela de preços, **não há lote em
rascunho a publicar**: composição é cadastro descritivo, e não existe estado
intermediário entre cadastrada e não cadastrada.

Antes da primeira carga, semeie as fibras:

```powershell
uv run python -m crm_api.admin_cli seed-fibers
```

Depois, com o cabeçalho de `composicao_exemplo.csv`:

```powershell
uv run python -m crm_api.imports.composition --file db/imports/composicao_exemplo.csv
```

Uma linha por fibra; o artigo é montado agrupando as linhas do mesmo SKU. O
artigo casa pelo **SKU**, que é a chave estável entre competências (ADR-021), e
a fibra pela sigla do setor — `PES`, `CV`, `CO`, `PUE`, `PA`, `EL`.

Um artigo cuja soma não fecha 100% é recusado **inteiro**: gravar metade da
composição faria a consulta por percentual mentir. A recusa não aborta o lote —
os demais artigos entram, e a saída lista SKU e motivo de cada recusado. O
comando devolve código 1 quando houve alguma recusa, para não passar despercebido
num script.

Artigo sem composição cadastrada continua aparecendo na busca e na tabela do
cliente exatamente como antes: **ausência não é negativa**, é cadastro por fazer.
