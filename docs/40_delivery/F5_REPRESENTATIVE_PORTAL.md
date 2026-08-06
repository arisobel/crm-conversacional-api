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

## R3 — Preço por competência — implementada em 2026-08-06

**Migração `0006`.** Cria `price_entries` e `price_entry_revisions`, adiciona
`PUBLISHED` a `price_list_status` e faz backfill da tabela ativa atual.

Esta é a etapa de maior risco: existe dado em produção no tenant
`empresa-textil` e o Gateway consome a rota de tabela vigente hoje.

Aceite — verificado por `tests/test_price_publication.py` e `tests/test_api.py`:

- Publicar promove os itens do lote e marca o lote como `PUBLISHED`.
- Republicar o mesmo lote é idempotente: nenhuma entrada duplicada e **nenhuma
  revisão vazia**, para que a trilha só conte o que de fato mudou.
- Corrigir o preço no meio do mês vira revisão com `previous` e `current` — o
  caso da tabela especial de 20/07, que deixa de ser uma segunda tabela.
- A alíquota do item prevalece sobre a do lote; nenhuma das duas é inventada.
- Competência futura não antecipa o preço: a leitura pega a mais recente que já
  chegou.
- O banco recusa dois preços para o mesmo `(tenant, competência, produto)`.
- Lote inexistente ou cancelado não publica e não deixa entrada.
- **Contrato do Gateway preservado:** `tests/test_api.py` teve apenas o fixture
  alterado para publicar o lote; todas as asserções da resposta permaneceram
  intactas e continuam passando.

Decisão tomada na implementação: o bloco `price_list` da resposta ao Gateway é
mantido e passa a descrever **o lote que publicou** os preços daquele mês. A
alternativa — expor a competência no lugar dele — quebraria o contrato que já
roda em produção.

Fora deste corte: a importação CSV com prévia continua sendo o script
`crm_api.imports.price_table`; a tela de importação é R6b.

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

## R4 — Motor de ICMS — implementada em 2026-08-06

**Migração `0007`.** Adiciona `tenants.origin_state_code`, cria `icms_rules` e
marca `tax_rules` como depreciada por comentário no banco.

**Q1 e Q2 continuam sem resposta contábil.** A implementação seguiu assim mesmo,
por decisão explícita, com três salvaguardas:

1. A fórmula é **selecionável** por `CRM_ICMS_CONVERSION_MODE`, com `INSIDE`
   (gross-up, ICMS por dentro) como padrão. Trocar para `OUTSIDE` é
   configuração, não migração.
2. **Nada é estimado.** Sem regra cadastrada o cálculo falha; sem UF de origem no
   tenant, idem. Nenhum preço chega a cliente antes de alguém carregar a matriz.
3. Cada item carrega o `trace` com regra, especificidade, alíquotas e valores
   intermediários — se a fórmula estiver errada, dá para provar item a item.

Aceite — verificado por `tests/test_icms.py`:

- Dois clientes idênticos em UFs diferentes recebem preços diferentes,
  explicáveis pelo trace.
- Regra de cliente prevalece sobre a de produto, que prevalece sobre o par puro.
- Duas regras igualmente específicas produzem erro, não escolha.
- Prioridade e depois vigência mais recente desempatam.
- Ausência de regra é `409`, não alíquota zero.
- Tenant sem UF de origem falha com mensagem clara.
- **A UF vem da localidade, não do cadastro do cliente**: um cliente registrado
  em RS que recebe numa filial em SP é precificado como SP.
- A lista usa o alias e a ordem definidos pelo cliente.
- Item indisponível não passa pelo cálculo — não haveria preço a exibir.
- Representante não administra a matriz.
- Valores monetários são `Decimal`, nunca `float`.

Fora deste corte: substituição tributária, DIFAL, redução de base, Simples
Nacional e frete. `freight_rules` permanece sem uso.

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

## R5 — Histórico de interações — implementada em 2026-08-06

**Migração `0008`.** Cria `customer_interactions` e o enum
`interaction_direction`.

Entregue:

- `POST /internal/interactions` — HMAC, escopo de tenant, lote de até 200
  eventos, idempotente por `(tenant, source, external_ref)` com unicidade no
  banco.
- Resolução do cliente pelo contato E.164 dentro do tenant, **inclusive contato
  desativado**: encerrar o atendimento por um número não deve fazer o CRM perder
  o registro do que veio por ele.
- `GET /admin/customers/{id}/interactions` paginada, com escopo de carteira.
- Retenção configurável em `CRM_INTERACTION_RETENTION_DAYS` e expurgo por
  `python -m crm_api.admin_cli purge-interactions`, com `--dry-run`.

**Três decisões que moldaram a implementação:**

`channel` é texto e `direction` é enum. Acrescentar e-mail ou telefone como
canal não deve exigir migração; direção só tem dois valores e a consulta filtra
por eles.

Cada evento grava em um savepoint próprio. Uma violação de unicidade em corrida
invalidaria a transação inteira e derrubaria o lote junto — o Gateway então
reenviaria para sempre os eventos que já haviam sido aceitos.

O expurgo sem política **falha**, em vez de assumir um prazo. Por quanto tempo
conteúdo de conversa pode ficar guardado é Q3, e um padrão embutido no código
tomaria essa decisão em silêncio.

Aceite — verificado por `tests/test_interactions.py` (23 testes):

- Reenviar o mesmo `external_ref` devolve `DUPLICATE` e a tabela continua com uma
  linha; referência repetida **dentro do mesmo lote** também.
- Evento sem cliente resolvido é recusado com motivo e os demais do lote são
  gravados; nada órfão entra na tabela.
- Um representante recebe `404` na timeline de cliente fora da sua carteira.
- O expurgo remove apenas o que passou do corte e grava a contagem em
  `audit_log`.
- A porta do Gateway não abre com cookie de sessão; assinatura inválida ou corpo
  alterado depois de assinado respondem `401`.

**Não entregue, e por isso registrado à parte:** o push do lado do Gateway. Ele
vive em outro repositório e o aceite "falha do CRM não impede o Gateway de
responder no WhatsApp" só pode ser satisfeito lá. O contrato completo está em
[F5_INTERACTION_PUSH_CONTRACT.md](F5_INTERACTION_PUSH_CONTRACT.md).

---

## R6 — Portal

Sem migração. Consome os mesmos serviços que as rotas administrativas.

**Q4 resolvida pelo ADR-017:** o portal é server-rendered com Jinja2, servido
pelo próprio processo FastAPI sob `/portal`. Mesma origem, para que o cookie de
sessão de R0 continue `SameSite=Lax` sem CORS nem token de CSRF por header.

### R6a — Telas de cadastro — implementada em 2026-08-05

Antecipada em relação ao plano. Ela não depende de R3–R5: tudo que essas telas
precisam já existia em R0–R2, e enquanto não existissem, popular a base exigia
PowerShell ou SQL.

| Tela | Rota | Conteúdo |
|---|---|---|
| Login | `/portal/login` | Autenticação; mesma sessão da API |
| Carteira | `/portal/customers` | Lista com filtro por busca, UF, situação e titularidade |
| Novo cliente | `/portal/customers/novo` | Cadastro, com titular quando o papel permite |
| Ficha do cliente | `/portal/customers/{id}` | Cadastro, titular, contatos e localidades |
| Representantes | `/portal/users` | Criação e ativação de usuários, somente `ADMIN` |

Aceite — verificado por `tests/test_portal.py`:

- Página protegida sem sessão redireciona para o login, não devolve JSON.
- Formulário sem token CSRF, ou com token forjado, é recusado com `400` antes de
  tocar o banco.
- Login inválido não distingue e-mail inexistente de senha errada.
- Logout encerra a sessão; a página seguinte volta ao login.
- Representante vê apenas a própria carteira e não recebe o menu de usuários.
- Cliente de outra carteira redireciona para a lista com "não encontrado".
- Cadastro de cliente cria a localidade padrão com a UF informada.
- Erros de domínio aparecem em português — "UF inválida", não a mensagem interna.
- Acentuação sobrevive ao ciclo formulário → banco → tela.
- Representante não transfere titular, e o cliente permanece inalterado.
- `ADMIN` não desativa a própria conta, nem pela tela nem por POST forjado.

### R6b — Telas dependentes — implementada em 2026-08-06

| Tela | Rota | Conteúdo |
|---|---|---|
| Tabela do mês | `/portal/prices` | Lotes, publicação, itens da competência e revisões; `ADMIN` |
| Matriz de ICMS | `/portal/icms-rules` | Regras vigentes e cadastro do par de UFs; `ADMIN` |
| Lista de preço | `/portal/customers/{id}/price-list` | Lista resolvida por localidade e competência, com trilha e exportação CSV |
| Timeline | ficha do cliente | Últimas 20 interações |
| Produtos preferidos | ficha do cliente | Inclusão, retirada, apelido e ordem |

**Escolhas de tela que carregam decisão de produto:**

Quando a lista de preço falha, a página continua de pé e mostra **o que
cadastrar** — "não há regra de ICMS para esse par de UFs", não um erro genérico.
Um redirecionamento perderia a localidade e a competência já selecionadas, e o
motivo é acionável: cada falha tem uma correção diferente e nenhuma é
automática.

O `trace` de cada item fica atrás de um `<details>` na própria linha. Enquanto
Q1 e Q2 não forem confirmadas, poder conferir item a item de onde saiu o número
vale mais do que uma tela limpa.

A importação continua sendo `python -m crm_api.imports.price_table`, e a tela
diz isso em vez de fingir que não existe. Upload de CSV pelo navegador entra
quando houver mais de uma pessoa carregando tabela; hoje há uma.

O CSV sai com BOM em UTF-8 e separador `;`, com decimal em vírgula. Sem o BOM o
Excel em português abre o arquivo na codificação da máquina e transforma cada
acento em ruído.

Aceite — verificado por `tests/test_portal_screens.py` (22 testes):

- O representante gera a lista de um cliente e a exporta sem passar por SQL.
- Lista sem regra de ICMS, sem UF de origem ou sem competência explica o que
  falta, e nenhum preço convertido aparece.
- Cliente fora da carteira não gera lista nem aceita alteração de preferidos.
- Republicar o mesmo lote não acrescenta revisão; lote cancelado não é
  publicável; publicação sem CSRF não toca o banco.
- Representante não alcança `/portal/prices` nem `/portal/icms-rules`.
- Retirar e reincluir um preferido reativa a linha e preserva o apelido.
- Toda resposta traz `Content-Security-Policy` com `frame-ancestors 'none'`,
  `X-Frame-Options: DENY` e `X-Content-Type-Options: nosniff`.
- `/docs` e `/openapi.json` respondem `404` por padrão, e só sobem com
  `CRM_EXPOSE_API_DOCS=true`.

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
| Conteúdo de conversa retido sem base legal | R5 não apaga por conta própria e recusa expurgar sem política; Q3 define o prazo |

## Ordem recomendada de execução

`R0 → R1 → R2 → R3 → (confirmar Q1/Q2) → R4 → R5 → R6`

Cada etapa entra com migração própria, reversível, testes de integração contra
PostgreSQL e atualização de `07_progress.md` e `09_backlog.md`.
