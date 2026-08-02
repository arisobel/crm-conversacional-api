# Regras de negócio

## Cliente e catálogo

- O contato é localizado por telefone E.164 dentro do tenant.
- Cada cliente pode possuir produtos preferenciais, ordem de exibição e alias comercial.
- O catálogo técnico não deve ser alterado apenas para reproduzir a linguagem de um cliente.

## Preço e vigência

- A tabela vigente é selecionada por tenant, status e intervalo de validade.
- `reference_month` representa o primeiro dia da competência.
- Preços, descontos, acréscimos e fretes são calculados deterministicamente.
- Disponibilidade possui estado controlado e pode incluir quantidade, data e observação.
- A consulta de tabela completa exibe somente preço-base por kg, disponibilidade e chegada.
  Desconto, prazo, frete e imposto não podem ser inferidos nem redigidos como valores até
  que regras determinísticas estejam cadastradas.
- A consulta específica pesquisa somente a tabela `ACTIVE` aplicável ao contato, por SKU,
  nome comercial, especificação ou família. Resultados múltiplos devem ser devolvidos de
  forma ordenada para escolha explícita; a LLM não seleciona silenciosamente um produto.

## Oferta

- A prévia calcula sem criar oferta.
- A criação persiste os dados usados no cálculo.
- Alterações posteriores de tabela não modificam itens já criados.
- Somente oferta aprovada pode ser enviada.
- Repetição da mesma chave de idempotência preserva o mesmo resultado lógico.

## LLM

- Pode identificar intenção e adaptar linguagem.
- Não pode executar SQL livre, inventar preço, criar exceção comercial ou autorizar envio.
