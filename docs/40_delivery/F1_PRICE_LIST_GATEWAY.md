# F1 — Tabela vigente no WhatsApp

## Resultado entregue

O contato autorizado no fluxo `crm_textil / consulta_cliente` pode enviar `tabela` pelo
WhatsApp. O Gateway resolve linha, fluxo e autorização e consulta o CRM pela rede interna
do CapRover. O CRM identifica o contato dentro de `empresa-textil`, seleciona a tabela
`ACTIVE` vigente e devolve itens estruturados.

O Gateway formata a mensagem por família e mostra nome comercial, especificação quando
existente, disponibilidade, chegada prevista e preço-base por kg.

## Comandos publicados

| Mensagem | Resultado |
|---|---|
| `tabela` | Lista completa da tabela vigente |
| `tabela de preço` | Equivalente a `tabela` |
| `tabela de preços` | Equivalente a `tabela` |
| outra mensagem | Lookup de cadastro e resposta de confirmação |

`produto <termo>` é o próximo comando planejado; ainda não está publicado neste corte.

## Contrato operacional

- CRM: `GET /price-lists/current/by-whatsapp/{phone}`.
- Cabeçalhos: `X-Tenant-Slug`, `X-Timestamp`, `X-Signature`.
- Assinatura: HMAC SHA-256 de `timestamp.method.path.body`; em `GET`, `body` é vazio.
- Gateway: `CRM_API_BASE_URL`, `CRM_API_TENANT_SLUG`, `CRM_API_HMAC_SECRET` e
  `CRM_API_TIMEOUT_MS` já configurados. Nenhuma variável adicional é necessária.
- Banco: a tabela deve estar `ACTIVE`; importações novas começam em `DRAFT` e exigem
  ativação explícita.

## Limites comerciais atuais

Os valores enviados são **preços-base por kg**. Não há, neste corte, cálculo de prazo,
antecipado, frete, imposto, quantidade mínima ou exceções por cliente. Esses valores não
devem aparecer como números até que regras determinísticas estejam cadastradas.

## Operação e diagnóstico

1. Confirme `GET /health` e `GET /ready` no CRM.
2. No PostgreSQL, confira a tabela ativa com `SELECT id, name, status, valid_from,
   valid_until FROM price_lists;`.
3. No Gateway, envie `tabela` de um telefone autorizado no fluxo CRM.
4. Procure `[CRM PRICE LIST RESOLVED]` no log do Gateway. Um `404` resulta em mensagem
   controlada de ausência de tabela vigente; falhas de HMAC, rede ou contrato não expõem
   detalhes internos ao cliente.

## Próxima entrega: consulta específica

O CRM pesquisará a tabela `ACTIVE` aplicável ao contato por SKU, nome comercial,
especificação e família. O Gateway reconhecerá:

```text
produto 75/36 urdume
produto TEX-75-36-URD
produto 44/40 talco
```

Resultado único gera uma ficha curta do item. Resultados múltiplos preservam SKU e
especificação para o contato escolher sem ambiguidade. A operação é somente de leitura e
não cria oferta, nem calcula prazo, frete, imposto ou desconto.

## Evolução: manifesto de capacidades

O CRM publica `GET /internal/interaction-capabilities`, assinado por HMAC, para que o
Gateway carregue na primeira mensagem da sessão as intenções e ações permitidas. O cache é
por `linha + fluxo + contato`, expira após 30 minutos de inatividade e contém somente
metadados de interpretação; não contém preço, dados de tabela ou mensagens.

O piloto é exclusivo do CRM. CKJ e Liondata não usam esse manifesto neste momento.

## Painel administrativo planejado

O painel será uma aplicação interna autenticada que usa operações administrativas da API
CRM; não acessará o PostgreSQL diretamente. O MVP abrange clientes/contatos,
famílias/produtos, importação CSV com prévia e divergências, revisão de itens, ativação de
tabela por usuário autorizado e auditoria das alterações.
