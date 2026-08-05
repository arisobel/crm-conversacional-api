# F5 — Portal do representante

Plano de entrega da [direção de CRM de representantes](../10_product/REPRESENTATIVE_DIRECTION.md),
sobre o [modelo-alvo](../20_domain/DOMAIN_MODEL_TARGET.md). Nada aqui está
implementado.

## Resultado esperado ao final

Um representante faz login, vê sua carteira, abre a ficha de um cliente, lê o
histórico de WhatsApp dele e gera a lista de preços com os produtos preferidos
daquele cliente, já convertida para o ICMS da UF onde ele recebe. Um
administrador publica a tabela do mês por CSV com revisão e ativação
auditáveis, e mantém a matriz de ICMS.

## Sequência

```text
R0 fundação de identidade
   └─ R1 representante e carteira ─┐
   └─ R2 localidades ──────────────┤
   └─ R3 preço por competência ────┴─ R4 motor de ICMS ─┐
                                                        ├─ R6 portal
                              R5 histórico de interações┘
```

R1, R2 e R3 são independentes entre si e podem correr em paralelo depois de R0.
R4 depende de R2 e R3. R6 depende de tudo.

---

## R0 — Fundação de identidade — implementada em 2026-08-05

**Migração `0003`.** Cria `users`, `user_sessions`, o enum `user_role` e
`audit_log`.

`user_sessions` não estava no plano original. Ela entrou porque o aceite exige
que desativar um usuário invalide sessões já emitidas e que o logout revogue de
fato — um token autocontido não faz nenhum dos dois sem uma lista de revogação,
que seria a mesma tabela com outro nome.

Entrega:

- Modelo ORM e repositório de `users`.
- Hash Argon2id, política mínima de senha, bloqueio após tentativas.
- Sessão por cookie `httpOnly` `SameSite=Lax` com expiração curta e renovação;
  desativar o usuário invalida sessões vigentes.
- Dependência de autorização por papel, separada do `verify_internal_request`
  HMAC — as rotas administrativas **não** compartilham o esquema do Gateway.
- Escrita em `audit_log` em toda mutação administrativa.
- CLI ou seed para criar o primeiro `ADMIN` sem SQL manual.

Aceite — verificado por `tests/test_auth.py`:

- Login válido devolve sessão; inválido não distingue e-mail inexistente, senha
  errada nem conta inativa.
- Rota administrativa sem sessão devolve `401`; com papel insuficiente, `403`.
- Nenhuma senha, hash ou token aparece em log, resposta ou trilha de auditoria.
- O banco guarda apenas o SHA-256 do token de sessão.
- Logout revoga a sessão: o mesmo cookie replicado depois recebe `401`.
- Desativar o usuário invalida imediatamente as sessões já emitidas.
- Falhas seguidas bloqueiam a conta mesmo que a senha correta venha depois.
- O limitador responde `429` antes de a tentativa chegar ao banco.
- Auditoria registra `LOGIN_SUCCEEDED`, `LOGIN_FAILED` e `LOGIN_BLOCKED`; a
  tentativa com e-mail inexistente é registrada sem tenant e sem ator.

Operação:

```bash
python -m crm_api.admin_cli create-user \
  --email admin@empresa.com.br --name "Nome Sobrenome" --role ADMIN
```

A senha vem de `CRM_SEED_PASSWORD` ou do terminal, nunca por argumento — a linha
de comando fica visível na lista de processos e no histórico do shell.

Pendências: aplicar a migração contra PostgreSQL; manter
`CRM_SESSION_COOKIE_SECURE=true` em produção; trocar o limitador em processo se
o serviço passar a rodar replicado.

---

## R1 — Representante e carteira — implementada em 2026-08-05

**Migração `0004`.** Adiciona `customers.owner_user_id` e cria
`customer_assignment_history`. Nenhum cliente existente recebe titular: a coluna
nasce nula e a designação é uma decisão comercial explícita.

Entrega:

- CRUD de usuários do portal, restrito a `ADMIN`:
  `POST/GET /admin/users`, `GET/PATCH /admin/users/{id}`,
  `POST /admin/users/{id}/activate|deactivate|password`.
- Designação, transferência e remoção de titular em
  `PUT /admin/customers/{id}/owner`, restrita a `ADMIN` e `MANAGER`.
- `GET /admin/customers/{id}/assignment-history` — trilha append-only.
- `GET /admin/customers` com escopo automático por papel.
- `GET /admin/me/customers` — a carteira de quem está logado.
- Filtros: UF, produto preferido, situação, com/sem titular e busca textual em
  razão social, nome fantasia e documento.

Aceite — verificado por `tests/test_portfolio.py` e `tests/test_admin_users.py`:

- Um representante que pede um `customer_id` de outra carteira recebe `404`,
  com o mesmo corpo de um `customer_id` inexistente.
- O escopo é aplicado na consulta ao banco; um teste exercita o repositório
  isolado, sem passar por rota nem serviço.
- Transferir titular grava histórico e não altera linhas antigas; reatribuir o
  titular vigente é um no-op e não polui a trilha.
- Remover o titular também é registrado, com `user_id` nulo.
- Titular proposto inexistente, inativo ou de outro tenant devolve `422` e não
  altera o cliente.
- Clientes sem titular aparecem apenas para `ADMIN` e `MANAGER`.
- Desativar um usuário revoga as sessões dele na mesma operação.
- Trocar a senha de um usuário revoga as sessões dele.
- Autodesativação e rebaixamento do último `ADMIN` ativo são recusados.

Decisões tomadas na implementação:

- **`POST /admin/users/{id}/password` não estava no plano.** Sem ela, um
  administrador não consegue socorrer quem esqueceu a senha, e o CRUD ficaria
  inutilizável na prática. Revoga sessões e é auditada.
- **A guarda do último `ADMIN` ativo também não estava no plano.** Desativar ou
  rebaixar a última conta administrativa trancaria todos para fora do portal sem
  caminho de recuperação pela própria aplicação.
- **O titular pode ser qualquer usuário ativo do tenant**, não só um
  `REPRESENTATIVE`. Restringir ao papel impediria um gerente de segurar contas
  durante uma transição.

Fora deste corte: o filtro por **data da última interação** depende de
`customer_interactions`, que só existe em R5. Ele entra junto com a timeline.

---

## R2 — Cadastro comercial e localidades — implementada em 2026-08-05

**Migração `0005`.** Cria `customer_locations` e faz backfill de uma localidade
padrão por cliente a partir de `customers.state_code`.

**Escopo ampliado em relação ao plano original.** R2 estava especificada apenas
como localidades, mas a nota de absorção do `ADMIN_INTERFACE_BACKLOG` dizia que
a Fase B — criar e editar cliente e contatos — cairia em R1 e R2, e nenhuma das
duas a tinha. Sem isso, cadastrar um cliente continuaria exigindo SQL, que é a
dor que originou o painel; e criar cliente, contato e localidade é a mesma tela.

Entrega:

- `POST /admin/customers` e `PATCH /admin/customers/{id}`.
- `GET/POST /admin/customers/{id}/contacts` e `PATCH .../contacts/{id}`.
- `GET/POST /admin/customers/{id}/locations` e `PATCH .../locations/{id}`.
- Índice parcial de unicidade da localidade padrão ativa, e o índice equivalente
  do contato principal declarado também no modelo ORM.
- Validação de UF contra as 27 unidades federativas, na aplicação — o `CHECK` do
  banco só garante o formato, e `XX` passaria por ele.

Aceite — verificado por `tests/test_customer_admin.py`:

- Todo cliente existente termina o backfill com exatamente uma localidade
  padrão, com a UF que já tinha.
- Criar um cliente já cria a sua localidade padrão na mesma transação.
- Marcar uma segunda localidade como padrão desmarca a anterior; o **banco**
  recusa duas padrão ativas, não apenas o serviço.
- Desativar ou desmarcar a localidade padrão devolve `422`: promover outra é
  escolha comercial, e o sistema não elege sozinho para onde a mercadoria vai.
- Telefone é normalizado para E.164 e é único por tenant; duplicado devolve `409`.
- Marcar um novo contato principal desmarca o anterior; desativar um contato
  também retira dele a marca de principal.
- Contato ou localidade pedidos através de um cliente de outra carteira devolvem
  `404` de cliente — não existe rota que os alcance por id solto.
- Um `REPRESENTATIVE` que cadastra cliente vira o titular; `owner_user_id` do
  corpo é ignorado para ele.
- A migração é reversível sem perda de `customers.state_code`.

---

## R3 — Preço por competência

**Migração `0006`.** Cria `price_entries` e `price_entry_revisions`, adiciona
`PUBLISHED` a `price_list_status` e faz backfill da tabela ativa atual.

Esta é a etapa de maior risco: existe dado em produção no tenant
`empresa-textil` e o Gateway consome a rota de tabela vigente hoje.

Entrega:

- `price_entries` como fonte de verdade, com `UNIQUE(tenant_id, reference_month, product_id)`.
- Publicação de lote: `price_lists` `DRAFT` → revisão → `PUBLISHED`, com `UPSERT`
  transacional em `price_entries` e gravação de revisão por linha.
- Importação CSV com prévia, relatório de linhas inválidas, SKU desconhecido,
  preço ausente e disponibilidade incoerente — antes de qualquer gravação.
- Reprocessar o mesmo lote não altera resultado nem gera revisão vazia.
- Histórico de revisões por produto e por competência na interface.
- Rota de leitura por competência, com fallback para a competência vigente.

Backfill:

- Os itens da tabela `ACTIVE` de 20/07/2026 viram `price_entries` da
  competência `2026-07`, com `source_batch_id` apontando para a `price_list`
  de origem e uma revisão inicial de `previous = null`.
- Se o backfill encontrar dois preços para o mesmo produto e mês, ele **para** e
  reporta o conflito. Não resolve por "último vence".

Compatibilidade:

- `GET /price-lists/current/by-whatsapp/{phone}` e a rota de busca de itens
  mantêm o contrato de resposta atual, passando a ler `price_entries`. O Gateway
  não muda nesta etapa.
- Teste de contrato compara a resposta antes e depois da migração para os dados
  de produção.

Aceite:

- Importar duas vezes a mesma competência não duplica preço.
- Uma correção de preço no meio do mês aparece como revisão, com autor e
  momento, e não como uma segunda tabela.
- O comando `tabela` no WhatsApp continua respondendo os mesmos valores.

---

## R4 — Motor de ICMS

**Migração `0007`.** Adiciona `tenants.origin_state_code`, cria `icms_rules` e
marca `tax_rules` como depreciada.

**Bloqueado por Q1 e Q2** da direção do produto: se o preço-base já contém ICMS
embutido e qual a forma de conversão. O modelo de dados não muda conforme a
resposta; só o serviço de cálculo.

Entrega:

- CRUD da matriz de ICMS, restrito a `ADMIN`, com vigência.
- Serviço de resolução determinística por especificidade, com erro explícito em
  empate e em ausência de regra.
- Serviço de conversão devolvendo preço para a UF, com `calculation_trace`
  contendo regra aplicada, alíquotas e valores intermediários.
- Rota de lista personalizada: dado um cliente e opcionalmente uma localidade e
  competência, devolve os produtos preferidos dele, na ordem e alias dele, com
  preço convertido.
- Importação da matriz por CSV para carga inicial das 27 UFs.

Aceite:

- Dois clientes idênticos em UFs diferentes recebem preços diferentes,
  explicáveis linha a linha pelo trace.
- Regra específica de cliente prevalece sobre regra de produto, que prevalece
  sobre o par de UF puro.
- Duas regras igualmente específicas e vigentes produzem erro, não escolha.
- Tenant sem `origin_state_code` falha com mensagem clara, não com alíquota zero.
- Nenhum valor monetário é calculado em `float`.

Fora deste corte: substituição tributária, DIFAL, redução de base, Simples
Nacional e frete. `freight_rules` permanece sem uso.

---

## R5 — Histórico de interações

**Migração `0008`.** Cria `customer_interactions`.

Entrega:

- `POST /internal/interactions` — HMAC, escopo de tenant, aceita lote,
  idempotente por `(source, external_ref)`.
- Resolução do cliente pelo contato E.164 dentro do tenant; evento sem cliente
  resolvido é rejeitado com erro controlado, não gravado órfão.
- Timeline paginada por cliente, com escopo de carteira.
- No Gateway: push assíncrono após tratar cada mensagem, com retry e sem
  bloquear a resposta ao contato.
- Política de retenção configurável e rotina de expurgo.

Aceite:

- Reenviar o mesmo `external_ref` não duplica e devolve o mesmo resultado.
- Falha do CRM não impede o Gateway de responder no WhatsApp.
- Um representante não lê a timeline de cliente fora da sua carteira.
- O expurgo remove apenas o que a política define e registra em `audit_log`.

---

## R6 — Portal

Sem migração. Consome apenas as rotas administrativas.

Telas:

| Tela | Conteúdo |
|---|---|
| Carteira | Clientes do representante, filtro por UF, produto e última interação |
| Ficha do cliente | Cadastro, localidades, contatos, produtos preferidos, timeline, tabela resolvida |
| Tabela do mês | Importar CSV, prévia, divergências, revisão, publicar, histórico de revisões |
| Matriz de ICMS | Regras por par de UF, vigência, especializações |
| Representantes | CRUD e transferência de carteira, somente `ADMIN` |

Decisão pendente (Q4): a interface vive em aplicação separada consumindo esta
API, ou é servida por este repositório. A recomendação é aplicação separada,
coerente com o ADR-011 — este repositório permanece uma API. A escolha não
altera nenhum contrato definido em R0–R5, e por isso pode ser decidida
imediatamente antes de R6.

Aceite:

- Nenhuma credencial de PostgreSQL chega ao navegador.
- Cabeçalhos de proteção contra clickjacking presentes.
- O representante gera a lista de um cliente e a exporta sem passar por SQL.

---

## Riscos transversais

| Risco | Mitigação |
|---|---|
| Dado em produção em `price_lists` | R3 com backfill que para em conflito e teste de contrato antes/depois |
| Gateway consome rota de tabela vigente | Contrato de resposta preservado em R3 |
| IDOR na carteira | Escopo no repositório, `404` em vez de `403`, teste dedicado |
| Regra fiscal errada vira preço errado ao cliente | Q1/Q2 confirmadas antes de R4; trace auditável por item |
| `MULTI_COMPANY_BACKLOG` reaparecer como requisito | Congelado e registrado no ADR-013 |
| Painel administrativo sem rate limit e sem política de segredo | R0 cobre; rodar `/security-review` antes de expor |

## Ordem recomendada de execução

`R0 → R1 → R2 → R3 → (confirmar Q1/Q2) → R4 → R5 → R6`

Cada etapa entra com migração própria, reversível, testes de integração contra
PostgreSQL e atualização de `07_progress.md` e `09_backlog.md`.
