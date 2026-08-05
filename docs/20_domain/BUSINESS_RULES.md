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

---

# Regras da nova direção — a implementar

Aprovadas em 2026-08-04 pelos ADRs 013 a 016. Ainda não valem em produção; o
plano está em [F5](../40_delivery/F5_REPRESENTATIVE_PORTAL.md).

## Representante e carteira

- Todo cliente tem no máximo um representante titular vigente.
- Um representante lê e escreve apenas clientes de sua carteira; o escopo é
  aplicado na consulta ao banco.
- Pedido de cliente fora da carteira responde "não encontrado", não "proibido".
- Transferir titular preserva o histórico anterior, com autor e motivo.
- Cliente sem titular só é visível para `ADMIN` e `MANAGER`.

## Preço por competência

- Existe um único preço vigente por `(tenant, competência, produto)`.
- Publicar a mesma competência de novo corrige o preço vigente; não cria uma
  segunda tabela nem duplica linhas.
- Toda gravação de preço produz uma revisão com valor anterior, novo, autor e
  momento.
- A importação continua entrando como lote `DRAFT` e exigindo revisão e
  ativação explícitas; só a ativação toca o preço vigente.
- Conflito no backfill ou na importação interrompe a operação e é reportado.
  Nunca se resolve por "último vence".

## Localidade e ICMS

- O preço entregue ao cliente depende da UF onde ele recebe.
- Um cliente pode ter mais de uma localidade; exatamente uma é a padrão ativa.
- A alíquota vem do par `UF de origem → UF de destino`, vigente na data de
  referência, com especialização opcional por produto, família e cliente.
- Precedência, da mais específica para a mais genérica: cliente+produto,
  cliente+família, cliente, produto, família, par de UF puro.
- Empate no mesmo nível resolve por prioridade e depois por vigência mais
  recente; empate remanescente é erro, não escolha silenciosa.
- Ausência de regra é erro. Não existe alíquota-padrão implícita.
- Todo preço convertido carrega o rastro do cálculo: regra aplicada, alíquotas
  e valores intermediários.
- Tenant sem UF de origem configurada falha com mensagem clara, nunca com
  alíquota zero.

## Lista personalizada

- A lista de um cliente contém seus produtos preferidos, na ordem e com o alias
  dele, com o preço já convertido para a UF da localidade escolhida.
- Cliente sem preferências recebe o catálogo ativo inteiro.

## Interações

- A ingestão de interação é idempotente por `(source, external_ref)`; reenvio
  não duplica.
- Evento sem cliente resolvido é rejeitado, nunca gravado órfão.
- Falha na ingestão pelo CRM não pode degradar o atendimento no canal.
- A timeline respeita o escopo de carteira do representante.
- Interações não sofrem alteração; a única remoção é a rotina de retenção
  auditada.
