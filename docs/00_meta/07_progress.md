# Progresso central

Atualizado em: 2026-09-02

## Estado atual

**Fase ativa:** F5 e W concluídas do lado do CRM. **R0 a R6 e W1 a W7
implementados e implantados.** Frente aberta: **D — campanhas de WhatsApp**
(ver [backlog](09_backlog.md)).

### F6 — plano de entrega de campanhas registrado (2026-09-02)

O roteiro aprovado de campanhas virou o plano de entrega
[F6_WHATSAPP_CAMPAIGNS](../40_delivery/F6_WHATSAPP_CAMPAIGNS.md): seis fases
(F6.0 decisões → F6.1 modelo → F6.2 resolvedor de audiência → F6.3 portal →
F6.4 integração com o Gateway → F6.5 conversacional), cada uma com critério de
saída. Nada implementado ainda. F6.1 e F6.2 podem começar sem integração
externa; F6.4 exige F6.0 fechada. A primeira entrega está pronta quando um
representante gera prévia restrita à própria carteira e salva um rascunho
auditável, sem nenhuma mensagem enviada.

Primeira pendência da F6.0 fechada no mesmo dia: **revisão nominal obrigatória
acima de 350 destinatários** (ADR-029), configurável com padrão 350.

### Verificado em produção em 2026-08-22

Conferido nas variáveis do CapRover e nos logs dos dois serviços após um "olá",
não por leitura de documentação:

- **A cadeia inteira `0001` → `0011` está aplicada.**
  `CRM_RUN_MIGRATIONS_ON_STARTUP=true` é honrada pelo `docker-entrypoint.sh`,
  que roda `alembic upgrade head` a cada start. As guardas da `0009` (colisão de
  telefone) e da `0006` (competência duplicada) **passaram**.
- **O manifesto canônico está ligado.** `mode: 'MANIFEST'` com
  `legacy_allowed: false` — o caminho legado já não é usado.
- **O push de interações roda nos dois sentidos**, INBOUND e OUTBOUND, com
  `created: 1` em ambos.
- **Nenhum número de representante foi autorizado ainda.** O log traz
  `actor_role: 'cliente'`. Todo o caminho de representante está construído dos
  dois lados e **nunca rodou de ponta a ponta**.

Três itens do backlog que estavam abertos e estavam prontos: o push assíncrono
no Gateway, os executores de representante (são quatro, não três) e a máquina de
confirmação do W7.

### N1 — conversa representante × cliente (2026-08-22)

**Migração `0012`.** A `0010` fixou que uma interação tem exatamente um dono, e
a regra estava certa para o caso dela: "bom dia" dito ao robô não pertence a
cliente nenhum. Mas representante conversando **com o cliente** é uma terceira
forma, com os dois donos, e o `CHECK` a recusava.

Entra o discriminador `kind` e o `CHECK` passa a exigir de cada forma o seu
formato exato — a alternativa, afrouxar para "pelo menos um dono", devolveria a
permissividade que a `0010` tinha tirado.

Uma invariante foi quebrada de propósito: **nota manual pode ser editada.** O
resto da tabela continua imutável. Nota é texto que uma pessoa escreveu, e
proibir corrigir só faria nascer uma segunda nota dizendo "corrigindo a
anterior" — dado pior do que o problema. Cada edição grava o texto anterior em
`audit_log`.

### D6 — grupo de artigo (2026-08-23)

**Migração `0013`.** O eixo de material do disparo ia derivar de
`product_families`. Não serve: "alta-tenacidade" é propriedade do fio de
poliéster, não um material ao lado dele, e o mesmo artigo é os dois.

Família não vira N↔N para acomodar isso — ela é **layout**, agrupa e ordena a
tabela impressa para o cliente, e um artigo em duas famílias não teria sob qual
cabeçalho sair. Entram `product_groups` e `product_group_members` ao lado,
N↔N, com `products.family_id` intocado.

`normalized_name` único é a guarda que importa: sem ela "poliester" e
"poliéster" nascem como dois grupos e o público de um disparo racha sem ninguém
perceber.

`/portal/products` passou a ser legível por representante, que também cria
grupo e etiqueta. Renomear, desativar, artigo e família continuam com a gestão.

### A decisão fiscal de 2026-08-22

**O sistema não calcula imposto.** O preço entregue é o preço-base, com o aviso
"em caso de incidência de impostos adicionais, eles serão acrescidos ao valor
base". Q1 e Q2 estão **dispensadas, não respondidas** — deixaram de importar.

O motor de ICMS do R4 fica dormente, não removido, com
`CRM_WHATSAPP_ICMS_ENABLED` desligado. A matriz das 27 UFs deixa de ser
pré-requisito de qualquer coisa.

**Mudança de direção em 2026-08-04:** o produto passa a ser um CRM operado por
representantes comerciais; o WhatsApp vira canal, não interface primária. Ver
[direção do produto](../10_product/REPRESENTATIVE_DIRECTION.md), ADRs 013 a 016
e o [plano de entrega F5](../40_delivery/F5_REPRESENTATIVE_PORTAL.md).

O que estava em andamento — consulta específica de produto no WhatsApp — não foi
cancelado, mas sai da frente da fila: entra depois de R3, quando o preço já
vier de `price_entries`.

## Concluído

- Separação entre WhatsApp Gateway e CRM Conversacional API.
- Modelo lógico inicial e migração PostgreSQL.
- Contrato OpenAPI inicial.
- Reorganização documental conforme a orquestração do projeto.
- Decisões centrais: competência mensal em colunas, cálculo determinístico, oferta imutável e aprovação humana.
- Stack F0 definida: Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2 assíncrono,
  asyncpg, Alembic, pytest, Ruff, Docker Compose e PostgreSQL 16.
- Serviço FastAPI com configuração por ambiente, `GET /health`, `GET /ready` e busca
  interna de cliente ativo por WhatsApp.
- Modelos ORM iniciais de tenant, cliente e contato; migração Alembic executável que
  aplica o DDL PostgreSQL aprovado.
- Contrato de escopo de tenant e HMAC com o WhatsApp Gateway registrado.
- Leitura interna da tabela `ACTIVE` por contato WhatsApp, com disponibilidade explícita
  e valores decimais estruturados, sem cálculo comercial implícito.
- Carga CSV revisada da tabela especial de 20/07/2026, ativada em produção para o tenant
  `empresa-textil`.
- Integração publicada no Gateway: o comando `tabela` consulta a lista vigente por HMAC,
  agrupa itens por família e exibe preço-base, indisponibilidade e chegada prevista.
- Especificação técnica exposta na resposta para distinguir itens com o mesmo nome
  comercial, como os itens Rubberflex.

- Planejamento da direção de CRM de representantes: direção do produto,
  modelo-alvo, plano de entrega R0–R6 e ADRs 013 a 016.
- **R0 — fundação de identidade.** Migração `0003` com `users`, `user_sessions`,
  `audit_log` e o enum `user_role`. Argon2id, política de senha, bloqueio por
  conta após falhas, limitador de tentativas em janela, sessão com estado no
  servidor (cookie httpOnly, janela deslizante e teto absoluto), autorização por
  papel separada do HMAC do Gateway, trilha de auditoria de login e CLI
  `python -m crm_api.admin_cli create-user`.

- **R1 — representante e carteira.** Migração `0004` com
  `customers.owner_user_id` e `customer_assignment_history`. CRUD de usuários do
  portal restrito a `ADMIN`, designação/transferência/remoção de titular com
  histórico append-only, `GET /admin/customers` e `GET /admin/me/customers` com
  escopo aplicado no repositório, e filtros por UF, produto preferido, situação,
  titularidade e busca textual.

- **R2 — cadastro comercial e localidades.** Migração `0005` com
  `customer_locations` e backfill de uma localidade padrão por cliente. CRUD de
  cliente, contatos e localidades pelo portal, com UF validada contra as 27
  unidades federativas, telefone normalizado em E.164 e único por tenant, e
  unicidade da localidade padrão e do contato principal garantida por índice
  parcial no banco. O escopo foi ampliado além do plano: o CRUD de cliente e
  contatos não tinha etapa dona, e sem ele cadastrar cliente ainda exigiria SQL.

- **R6a — telas de cadastro do portal.** Antecipada: não dependia de R3–R5 e
  era o que faltava para popular a base sem PowerShell. Portal server-rendered
  com Jinja2 sob `/portal`, na mesma origem da API (ADR-017, que revisa a
  recomendação anterior de aplicação separada). Login, carteira com filtros,
  ficha do cliente com contatos e localidades, transferência de titular e tela
  de representantes. Proteção CSRF por double-submit cookie.

## Verificado em produção

- Migrações `0003`, `0004` e `0005` aplicadas; `alembic current` em
  `0005_customer_locations`. As quatro tabelas novas existem e o backfill da
  `0005` criou a localidade `Principal` para os dois clientes, com a UF
  preservada.
- Login e sessão do portal funcionando sobre HTTPS: `POST /admin/auth/login`
  emite o cookie e `GET /admin/auth/me` o aceita.

- **R3 — preço por competência.** Migração `0006` com `price_entries` e
  `price_entry_revisions`. Publicação de lote com `UPSERT` e revisão por linha,
  idempotente ao republicar. A leitura consumida pelo Gateway passou a vir de
  `price_entries` com o contrato de resposta intacto — `tests/test_api.py` teve
  só o fixture alterado e todas as asserções continuam passando.
- **R4 — motor de ICMS.** Migração `0007` com `tenants.origin_state_code` e
  `icms_rules`. Resolução por especificidade em seis níveis, com erro explícito
  em empate e em ausência de regra. Conversão com trace por item e fórmula
  selecionável em `CRM_ICMS_CONVERSION_MODE`. Rota de lista resolvida por
  cliente e localidade, e CRUD da matriz restrito a `ADMIN`.

- **R5 — histórico de interações.** Migração `0008` com `customer_interactions`.
  Ingestão em lote por HMAC, idempotente por `(tenant, source, external_ref)`,
  com savepoint por item para que um evento recusado não derrube o lote.
  Timeline paginada com escopo de carteira, filtro de carteira por última
  interação e expurgo auditado que **recusa rodar sem política de retenção**.

- **R6b — telas dependentes.** Tabela do mês com publicação e revisões, matriz
  de ICMS, lista de preço resolvida por cliente com trilha e exportação CSV,
  timeline e produtos preferidos na ficha. Cabeçalhos contra clickjacking em
  toda resposta e `/docs` desligado por padrão.

- **Tabela do WhatsApp por cliente.** A rota consumida pelo Gateway passa a ter dois
  regimes, escolhidos por `CRM_WHATSAPP_ICMS_ENABLED`. Desligado (padrão), o
  comportamento é byte a byte o de hoje. Ligado, ela devolve **só os produtos
  preferidos** do cliente, na ordem dele, com o preço **convertido para a UF onde ele
  recebe** — delegando ao mesmo serviço que o portal usa — e com erros distinguíveis:
  `404` só para contato desconhecido, `409` para regra de ICMS ausente ou ambígua,
  `422` para falta de localidade, de UF de origem ou de competência.
  Os campos `final_price`, `tax_rate`, `origin_state` e `destination_state` são
  **aditivos**: um Gateway anterior continua lendo `base_price` e funcionando.

- **R6c — cadastro de artigo pela ficha.** Sem migração. O `<select>` de
  produtos preferidos virou um combobox com busca por nome, SKU e família,
  insensível a acento, escrito sem dependência externa — a CSP é
  `default-src 'self'` e nenhum CDN carregaria. Quando o artigo não aparece na
  busca, a própria lista oferece cadastrá-lo: o produto entra no catálogo na
  hora e o preço entra como item de um lote `DRAFT` da competência corrente,
  que continua exigindo publicação (ADR-020). Restrito a `ADMIN` e `MANAGER`.
  Sem JavaScript o `<select>` nativo continua funcionando e o formulário do
  artigo aparece aberto na página.

- **R6d — catálogo de produtos.** Sem migração. `/portal/products` passa a
  manter o catálogo que antes só nascia por CSV: lista com filtros, cadastro
  com preço opcional, edição de nome, especificação, unidade e família,
  desativação lógica, e CRUD de famílias com a ordem que agrupa a tabela do
  WhatsApp. Fecha a Fase C do backlog administrativo, pendente desde F1.

  A decisão que essa tela força está no ADR-021: com duas fontes descrevendo o
  mesmo artigo, **o cadastro é dono do nome** e a planilha do preço. O
  importador deixa de abortar por nome divergente — mantém o do cadastro e
  reporta as divergências — e o SKU trava no primeiro preço publicado, porque é
  por ele que a planilha reencontra o artigo.

## Em andamento

- **Frente D — disparo para grupo de clientes.** Em desenho; nada em código.
  Decidido: segmentação em dois eixos (material e porte), remetente é a linha
  BPTI, template da Meta em aprovação, disparo por link como caminho secundário.
- **Frente N — conversa representante × cliente na ficha.** N1 (nota manual)
  implementada em 22/08 pela migração `0012`; N2 (envio pelo portal) depende da
  rota de envio CRM → Gateway, compartilhada com o disparo.

## Próximo baby-step

1. **Autorizar um número de representante no painel do Gateway.** É o único
   passo que falta para W4, W6 e W7 rodarem de ponta a ponta — quatro
   executores, manifesto e máquina de confirmação já estão prontos e ligados dos
   dois lados, e nada disso jamais foi exercido com um representante real.
2. **Modo "sem conversão" em `CustomerPriceListService.resolve`.** Ele passa
   sempre pelo resolvedor de ICMS; sem matriz carregada, a tela de lista
   resolvida por cliente do portal **não funciona**. A decisão de 22/08 torna
   isso um defeito aberto, não uma pendência de dado.
3. **Publicar uma competência** em `/portal/prices` e cadastrar os produtos
   preferidos dos clientes; sem eles a tabela sai como catálogo inteiro.
4. **Confirmar Q3** e configurar `CRM_INTERACTION_RETENTION_DAYS`. A variável
   não existe no CapRover, conferido em 22/08: nada é apagado — o que é seguro,
   mas não é uma política.
5. **Registrar a decisão fiscal como ADR.** Sem ela, a matriz de ICMS vazia
   parece esquecimento em vez de escolha.

## Pendências abertas

- Nenhuma migração é executada contra PostgreSQL no ambiente de
  desenvolvimento — não há Docker nem banco aqui; a validação é a cadeia de
  revisões (`0011_customer_intakes` é head) e o esquema equivalente sobre SQLite
  nos testes. **Em produção elas rodam sozinhas**, no start do contêiner, e é aí
  que a verificação real acontece.
- **`alembic upgrade head` automático no start não tem passo de revisão.** Um
  deploy com migração ruim derruba o start do contêiner. Funciona para uma
  pessoa; não sobrevive a duas. Ninguém decidiu manter ou tirar.
- Interação de contato não cadastrado volta como `REJECTED` e **não é
  reenfileirada**: cadastrar o contato depois não traz de volta o que já foi
  recusado. Só as mensagens seguintes entram na timeline.
- `CRM_EXPOSE_API_DOCS` passou a valer `false` por padrão. Quem usava `/docs` em
  produção precisa ligá-lo explicitamente, ou passar a ler
  `openapi/crm-api.yaml`.
- Q3 sem resposta: `CRM_INTERACTION_RETENTION_DAYS` não está configurada e o
  expurgo recusa rodar. Nada é apagado enquanto isso.
- A `0006` é a mais delicada de todas até agora: ela verifica conflitos antes de
  gravar e **aborta a transação inteira** se encontrar duas tabelas `ACTIVE` com
  o mesmo produto e competência, em vez de resolver por "último vence".
- **Q1 e Q2 foram dispensadas em 2026-08-22**, não respondidas. O sistema não
  calcula imposto; entrega o preço-base com aviso. Se um dia o cálculo voltar,
  as duas perguntas contábeis voltam junto — elas não foram resolvidas, só
  deixaram de estar no caminho.
- `CRM_SESSION_COOKIE_SECURE` precisa permanecer `true` em produção; só os
  testes o desligam. **Não está definida no CapRover**, e o padrão do código é
  `true` — correto hoje, mas por omissão e não por configuração.
- O limitador de login tem estado em processo. Com mais de uma réplica, ele
  precisa migrar para armazenamento compartilhado; o bloqueio por conta em
  `users.locked_until` é o controle que já atravessa réplicas.
- Nenhum cliente de produção tem titular. A carteira só passa a existir quando
  um administrador designar os titulares pelo portal.

- **`CRM_WHATSAPP_ICMS_ENABLED` está desligado e passa a ser permanente**, pela
  decisão de 22/08. Não está definida no CapRover; o padrão do código é `false`,
  que é o desejado. O interruptor deixa de ser transitório e vira o mecanismo que
  mantém R4 dormente.
- **`CustomerPriceListService.resolve` passa sempre pelo resolvedor de ICMS.**
  Sem matriz carregada — e ela não será carregada — a tela de lista resolvida por
  cliente do portal não funciona. Era pendência de dado; a decisão de 22/08
  transformou em defeito aberto.
- **Nota manual não pode ser excluída, só corrigida.** Uma nota lançada no
  cliente errado fica na ficha dele; o que sobra é reescrevê-la para "lançamento
  indevido". Falta decidir se some ou se é marcada.

## Evidências

- DDL: `db/migrations/0001_initial.sql`
- OpenAPI: `openapi/crm-api.yaml`
- Critérios: `docs/50_validation/ACCEPTANCE_CRITERIA.md`
- Operação F1: `docs/40_delivery/F1_PRICE_LIST_GATEWAY.md`
