# Backlog priorizado

Direção vigente: [CRM de representantes](../10_product/REPRESENTATIVE_DIRECTION.md).
Plano de entrega: [F5](../40_delivery/F5_REPRESENTATIVE_PORTAL.md).

## P0 — Decisões que bloqueiam implementação

- [x] ~~Q1 — o preço-base já contém ICMS embutido?~~ **Dispensada em 2026-08-22.**
- [x] ~~Q2 — conversão "por dentro" ou acréscimo simples?~~ **Dispensada em 2026-08-22.**
- [ ] Definir retenção e visibilidade do histórico de interações sob LGPD (Q3).
- [x] Q4 — a interface é server-rendered na mesma origem da API (ADR-017).

**Decisão administrativa de 2026-08-22: o sistema não calcula imposto.** O preço
entregue é o preço-base, acompanhado do aviso "em caso de incidência de impostos
adicionais, eles serão acrescidos ao valor base". Isso encerra Q1 e Q2 por
dispensa, não por resposta: a pergunta contábil continua sem responder, e deixou
de importar porque ninguém depende mais dela.

O motor de ICMS do R4 **não é removido** — fica dormente com
`CRM_WHATSAPP_ICMS_ENABLED` desligado, que já é o padrão e é o que está em
produção. Se a decisão mudar, o código está pronto e testado.

- [ ] Registrar a decisão como ADR. Sem ela, daqui a um ano a matriz de ICMS
      vazia parece esquecimento em vez de escolha.
- [ ] Modo "sem conversão" em `CustomerPriceListService.resolve`, que hoje passa
      sempre pelo resolvedor de ICMS. Sem matriz carregada, a tela de lista
      resolvida por cliente do portal **não funciona**. O `trace` continua
      existindo e passa a registrar que não houve cálculo.

Q3 não bloqueou R5. O que ela decide é o **prazo** de retenção, e enquanto não
houver decisão o sistema não apaga nada: o expurgo recusa rodar sem política.

## Migrações em produção — verificado em 2026-08-22

`CRM_RUN_MIGRATIONS_ON_STARTUP=true` está configurada no CapRover e é honrada
pelo `docker-entrypoint.sh`, que roda `alembic upgrade head` **a cada start do
contêiner**. Como a produção está servindo o código de `0a8c5af` (2026-08-19,
que já inclui a `0011`) e respondendo requisições em 2026-08-22, a cadeia
inteira `0001` → `0011` está aplicada.

Isso encerra por evidência, e não por execução manual, os itens de "aplicar a
migração X contra PostgreSQL" que estavam abertos em R0, W1, W4 e W7.

Duas consequências que valem registro, porque são guardas que **passaram**:

- A `0009` aborta se encontrar um telefone que seja usuário do portal e contato
  de cliente ao mesmo tempo. O contêiner subiu, logo não há colisão hoje.
- A `0006` aborta se houver duas tabelas `ACTIVE` com o mesmo produto e
  competência. Também passou.

O risco que essa configuração cria e que ninguém decidiu ainda: **um deploy com
migração ruim derruba o start do contêiner**, e não há passo de revisão entre
publicar e migrar. Funciona bem para uma pessoa; não sobrevive a duas.

- [ ] Decidir se `alembic upgrade head` continua automático no start.

## R0 — Fundação de identidade (implementada)

- [x] Migração `0003`: `users`, `user_sessions`, `audit_log`, enum `user_role`.
- [x] Hash Argon2id, política de senha e bloqueio por tentativas.
- [x] Sessão segura, revogada ao desativar o usuário e no logout.
- [x] Autorização por papel, separada do HMAC do Gateway.
- [x] Rate limit no login.
- [x] Seed do primeiro `ADMIN` sem SQL manual (`crm_api.admin_cli`).
- [x] Aplicar a migração `0003` contra PostgreSQL — ver "Migrações em produção".
- [ ] Substituir o limitador em processo caso o serviço passe a rodar replicado.

## R1 — Representante e carteira (implementada)

- [x] Migração `0004`: `customers.owner_user_id`, `customer_assignment_history`.
- [x] CRUD de representantes, com troca de senha e guarda do último `ADMIN`.
- [x] Designação, transferência e remoção de titular com motivo e histórico.
- [x] `GET /admin/me/customers` e `GET /admin/customers` com escopo por papel.
- [x] Teste de isolamento de carteira na camada de repositório.
- [x] Filtro por data da última interação — entregue junto com R5.

## R3 — Preço por competência (implementada)

- [x] Migração `0006`: `price_entries`, `price_entry_revisions`, status `PUBLISHED`.
- [x] Publicação de lote com `UPSERT` transacional e revisão por linha.
- [x] Backfill da tabela ativa, interrompendo em conflito de competência.
- [x] Teste de contrato antes/depois nas rotas consumidas pelo Gateway.
- [ ] Importação CSV com prévia e divergências pela interface — R6b.

## R2 — Cadastro comercial e localidades (implementada)

- [x] Migração `0005`: `customer_locations` e backfill da UF atual.
- [x] CRUD de localidades com unicidade da padrão ativa, garantida pelo banco.
- [x] Validação de UF contra as 27 unidades federativas.
- [x] CRUD de cliente — absorvido da Fase B do backlog administrativo.
- [x] CRUD de contatos com E.164, unicidade por tenant e contato principal.

## R4 — Motor de ICMS (implementada)

- [x] Migração `0007`: `tenants.origin_state_code`, `icms_rules`, depreciar `tax_rules`.
- [x] Resolução determinística por especificidade, com erro em empate e em ausência.
- [x] Conversão de preço com trace auditável e fórmula selecionável.
- [x] Rota de lista personalizada por cliente, localidade e competência.
- [x] CRUD da matriz por API, restrito a `ADMIN`.
- [x] ~~Carga CSV inicial da matriz das 27 UFs.~~ **Cancelada pela decisão de
      2026-08-22:** não há cálculo de imposto, logo não há matriz a carregar.
- [x] ~~Confirmar Q1/Q2 antes de qualquer preço ir a cliente.~~ Dispensada.

**R4 fica dormente, não removida.** Todo o motor continua no código, testado, e
`CRM_WHATSAPP_ICMS_ENABLED` desligado é o que garante que nada dele alcance um
cliente. Reativar é decisão comercial mais carga da matriz, não desenvolvimento.

## R5 — Histórico de interações (implementada)

- [x] Migração `0008`: `customer_interactions` e enum `interaction_direction`.
- [x] `POST /internal/interactions` idempotente por `(tenant, source, external_ref)`.
- [x] Timeline paginada por cliente, com escopo de carteira.
- [x] Rotina de expurgo auditada, que recusa rodar sem política definida.
- [x] Filtro de carteira por última interação — desbloqueia o pendente de R1.
- [x] **Push assíncrono no Gateway**, com retry e sem bloquear a resposta ao
      contato. **Implementado e verificado em produção em 2026-08-22.**
      `modules/crm_interaction_push.js` tem fila, retry com backoff, desistência
      e teto de fila. É enfileirado nos dois sentidos: INBOUND em `server.js:5272`,
      **antes** de qualquer processamento — se a resolução de intenção falhar, o
      representante ainda vê que o cliente escreveu — e OUTBOUND a cada resposta
      do bot, em `server.js:4930`. Contrato em
      [F5_INTERACTION_PUSH_CONTRACT](../40_delivery/F5_INTERACTION_PUSH_CONTRACT.md).
- [ ] Definir Q3 e configurar `CRM_INTERACTION_RETENTION_DAYS`. **A variável não
      existe no CapRover**, conferido em 2026-08-22: o expurgo recusa rodar e
      nada é apagado.
- [ ] Agendar a execução periódica do expurgo.
- [x] **A timeline passa a aceitar representante ↔ cliente** — ver N1 abaixo.
- [ ] **Nenhum aviso ao representante** quando o cliente escreve. Ele precisa
      abrir a ficha para descobrir.

## N — Conversa representante × cliente na ficha

### N1 — Nota manual (implementada em 2026-08-22)

**Migração `0012`.** O `ck_interaction_exactly_one_owner` da `0010` recusava a
linha com cliente e usuário juntos — a forma exata de uma conversa entre
representante e cliente. Entra o discriminador `kind` e o `CHECK` passa a exigir
de cada forma o seu formato, em vez de afrouxar para "pelo menos um dono".

Verificada por `tests/test_representative_notes.py` (17) e
`tests/test_portal_notes.py` (7). A suíte inteira está em 379 verdes.

- [x] `kind` com as três formas, `CHECK` por forma e backfill derivado do dono
      que cada linha já tinha. Nenhuma linha existente muda.
- [x] `direction` nulável, exigida só das formas de canal — "visitei o cliente"
      não é recebida nem enviada.
- [x] Registro na ficha com meio (telefone, visita, WhatsApp, e-mail, outro) e
      sentido opcional. O autor é sempre quem está logado.
- [x] **Nota é editável; evento de canal não.** É a única escrita que altera uma
      linha desta tabela. Cada correção grava em `audit_log` com o texto
      anterior, e `edited_at` mostra a marca sem consultar a trilha.
- [x] Autor corrige a própria; `ADMIN` e `MANAGER` corrigem qualquer uma.
- [x] Escopo de carteira aplicado no registro e na correção.
- [ ] Aplicar a `0012` contra PostgreSQL. Ela roda sozinha no próximo deploy;
      confirmar nos logs de start.
- [ ] Excluir nota. Hoje só dá para corrigir o texto — uma nota lançada no
      cliente errado fica lá, e corrigi-la para "lançamento indevido" é o que
      sobra. Falta decidir se some ou se é marcada.
- [ ] Filtrar a timeline por origem. Com nota e canal na mesma lista, quem
      procura só o que passou pelo WhatsApp não tem como recortar.

### N2 — Envio pelo portal pela linha BPTI

Compartilha a rota de envio CRM → Gateway com o D3; fazer as duas juntas.

- [ ] Mensagem enviada pelo portal ao cliente, gravada como interação.
- [ ] A resposta já volta sozinha pelo push, que roda nos dois sentidos.

## R6e — Gestão de acesso pela tela (implementada em 2026-08-22)

Sem migração. Três operações que existiam no serviço e na API mas não tinham
botão: um representante que esquecesse a senha dependia de alguém chamar a API
na mão, não podia trocar a senha recebida, e não havia como corrigir o cadastro
dele — inclusive o WhatsApp, que é a identidade dele no canal.

- [x] Redefinir senha em `/portal/users`, restrito a `ADMIN`. Derruba as sessões
      do usuário e libera o bloqueio por tentativas.
- [x] `/portal/minha-senha` — troca da própria senha, para qualquer papel.
      **Exige a senha atual**: sem isso, um cookie roubado trancaria o dono
      fora da própria conta. Derruba as **outras** sessões e mantém a atual;
      revogar tudo derrubaria quem acabou de trocar, e o logout imediato se lê
      como falha.
- [x] Editar nome, papel e WhatsApp na tela, com o número na listagem.
- [x] Tentativa de troca com senha atual errada grava
      `USER_PASSWORD_CHANGE_REFUSED` — **e a rota faz commit na recusa**, porque
      o rollback apagaria justamente o registro que interessa investigar.
- [x] O portal limpa o WhatsApp; a API não consegue. Lá o schema valida contra
      E.164 e `None` significa "não mexa", então "apague" é inexprimível.
- [ ] **A tela de auditoria continua não existindo.** `LOGIN_SUCCEEDED`,
      `LOGIN_FAILED`, `LOGIN_BLOCKED`, `USER_PASSWORD_RESET` e as duas novas são
      gravadas, e nenhuma rota lê `audit_log`. Hoje só por SQL. Fica mais
      urgente conforme representantes reais começarem a entrar.
- [ ] Remover o WhatsApp aqui **não** tira a autorização do número no painel do
      Gateway — a consequência que o ADR-022 aceitou explicitamente. A tela
      avisa; a mitigação continua sendo a `/portal/whatsapp` da W5.

## R6a — Telas de cadastro (implementada)

- [x] Login, logout e sessão com redirecionamento em vez de `401` JSON.
- [x] Proteção CSRF por double-submit cookie, cobrindo o formulário de login.
- [x] Tela de carteira com filtros e escopo por papel.
- [x] Cadastro e edição de cliente, contatos e localidades.
- [x] Transferência de titular pela ficha do cliente.
- [x] Tela de representantes e ativação de usuários.

## R6b — Telas dependentes (implementada)

- [x] Tela da tabela do mês: lotes, publicação, competência e revisões.
- [x] Tela da matriz de ICMS e lista resolvida por cliente, com exportação CSV.
- [x] Timeline de interações na ficha do cliente.
- [x] Produtos preferidos por cliente na ficha, com apelido e ordem.
- [x] Cabeçalhos contra clickjacking e `/docs` desligado por padrão.
- [ ] Importação CSV pelo navegador, com prévia e divergências. Hoje a carga é
      por linha de comando, o que basta para uma pessoa carregando tabela.

## R6c — Cadastro de artigo pela ficha (implementada)

- [x] Combobox com busca por nome, SKU e família, insensível a acento, sem
      dependência externa e degradando para o `<select>` nativo sem JavaScript.
- [x] Modal de cadastro de artigo, restrito a `ADMIN` e `MANAGER`, aberto pela
      própria busca quando o artigo não aparece.
- [x] O artigo entra no catálogo e o preço entra como item de lote `DRAFT` da
      competência corrente; publicar continua sendo um ato separado (ADR-020).
- [x] Família nova ou existente, reaproveitada pelo nome.
- [x] Marca "sem preço no mês" no preferido que ainda não tem entrada publicada.
- [x] Editar artigo já cadastrado — entregue em R6d.
- [ ] Corrigir o item do rascunho antes de publicar. Não há tela para isso nem
      para cancelar o lote; um preço digitado errado hoje se corrige publicando
      e republicando por cima, o que deixa a revisão registrada — funciona, mas
      documenta um engano de digitação como mudança comercial.

## R6d — Catálogo de produtos (implementada)

Fase C do [backlog administrativo](../40_delivery/ADMIN_INTERFACE_BACKLOG.md),
que estava pendente desde F1. Sem migração.

- [x] `/portal/products`: lista com SKU, nome, especificação, família, unidade,
      preço da competência, quantos clientes preferem e situação.
- [x] Filtros por busca textual, família, situação e "só sem preço no mês".
- [x] Cadastro de artigo com preço **opcional** — diferente do modal da ficha,
      aqui o artigo sem preço é caso normal.
- [x] Edição de nome, especificação, unidade e família.
- [x] SKU editável só enquanto não houver preço publicado (ADR-021).
- [x] Ativação e desativação lógica, preservando as preferências dos clientes.
- [x] CRUD de famílias com ordem de exibição, que é o agrupamento da tabela do
      WhatsApp — antes só mudava por SQL.
- [x] Importação de CSV deixa de abortar por nome divergente: mantém o cadastro
      e reporta as divergências (ADR-021).
- [x] Marca "artigo desativado" no preferido, na ficha do cliente.
- [ ] Prévia da linguagem que o WhatsApp exibirá para cada produto — item da
      Fase C que continua fora.
- [ ] Reordenar artigo dentro da família pela tela; hoje a ordem do item vem do
      `display_order` da planilha.

## Tabela do WhatsApp por cliente (implementada, desligada)

- [x] Campos `final_price`, `tax_rate`, `origin_state` e `destination_state`, aditivos.
- [x] Recorte por produtos preferidos e conversão de ICMS, reusando o serviço do R4.
- [x] `409` e `422` distinguindo falha fiscal de contato desconhecido.
- [x] Interruptor `CRM_WHATSAPP_ICMS_ENABLED`, padrão desligado.
- [ ] Adaptar o formatador do Gateway para preferir `final_price` e tratar `409`/`422`.
- [ ] **Ligar o interruptor só depois de Q1/Q2 confirmadas e da matriz carregada.**

## W — Manifesto por ator no WhatsApp

Desenho em [WHATSAPP_ACTOR_MANIFEST.md](../30_architecture/WHATSAPP_ACTOR_MANIFEST.md),
decisões nos ADR-022 a ADR-024.

### W1 — Identidade do ator (implementada em 2026-08-16)

**Migração `0009`.** Canoniza `users.whatsapp_e164`, cria o índice parcial de
unicidade e acrescenta `public_ref` a `users` e `customer_contacts`.

Verificada por `tests/test_whatsapp_actor_identity.py` (13 testes).

- [x] Aplicar a `0009` contra PostgreSQL — aplicada no start; ver "Migrações em
      produção". A guarda de colisão passou, logo hoje nenhum telefone é usuário
      do portal e contato de cliente ao mesmo tempo.
- [ ] Agendar `python -m crm_api.admin_cli check-whatsapp-identities`. A guarda
      da `0009` só olha o momento da migração; a colisão pode nascer depois.

### W2 — Bloqueio no Gateway, antes de tudo

- [x] Estender o `business-capability-manifest/v1` com `vocabulary` e `slots`
      por capacidade, e generalizar o validador por provider (`GW-010`).
      Entregue no Gateway em `e122bb6`, com fixture companheira e a mínima
      intocada. Limites acordados espelhados no desenho.
- [x] Registrar no Gateway o tipo de slot `product_code` (ADR-025, DEC-046 de
      lá). Regex extraída byte a byte; suíte de lá em 87 verde.
- [ ] **Dívida do Gateway, não bloqueia:** `actor.id` valida contra
      `^[a-f0-9]{24}$`, que é forma de `ObjectId` do Mongo escrita como se fosse
      regra genérica do envelope. O `public_ref` casa por construção; a terceira
      aplicação é que vai esbarrar.
- [ ] `kind` só passa a ter efeito com o `GW-021`, aberto. Até lá, declará-lo não
      muda resolução nenhuma — considerar na W6.
- [ ] **Bug do Gateway, medido em 2026-08-16 com o manifesto real.** Dentro do
      `resolveBusinessCapabilityIntentByRules`, o casamento de alias é insensível
      a acento e o preenchimento de slot por prefixo é sensível. `"preço do PUE
      20"` resolve; `"preco do PUE 20"` não resolve nada — o alias casa, o slot
      obrigatório fica faltando e a mensagem cai na LLM. Digitar sem acento é o
      caso comum no WhatsApp.
- [ ] **Registrar os IDs de slot esperados por ação**, do mesmo jeito que `kind`
      é registrado. `server.js` lê `resolution.slots.product_query` por nome
      literal; um manifesto com outro nome passa pela validação inteira e chega
      ao executor com o campo vazio.
- [ ] Observabilidade: o painel (`GW-081`) não cobre o provider `crm_api`.

### W3 — Resolução de ator e manifesto canônico (implementada em 2026-08-16)

Sem migração. `POST /api/integrations/whatsapp/v1/capabilities/manifest`,
`WhatsappActorResolver` e o `GET` legado intocado.

Verificada por `tests/test_capability_manifest.py` (16 testes), dois deles
validando a resposta contra o schema do Gateway campo a campo.

**O representante recebe `capabilities: []`.** Não é lacuna: os dois executores
de hoje resolvem a tabela pelo telefone de quem escreveu, procurando um cliente,
e falhariam para ele. Anunciar ação sem executor faria a allowlist do Gateway
recusar o manifesto **inteiro** e deixar o contato sem resposta. As capacidades
dele entram na W6, junto com os executores.

**Atualização de 2026-08-22: o representante não recebe mais `capabilities: []`.**
O serviço já emite as quatro capacidades dele, incluindo o pré-cadastro. O
parágrafo acima descreve o estado de 16/08 e fica como histórico.

- [x] Publicar antes de o Gateway ligar a flag — feito; a flag lá já está ligada.
- [ ] Congelar o `GET /internal/interaction-capabilities`. **Agora é acionável:**
      a flag virou no Gateway e o log de produção mostra `mode: 'MANIFEST'` com
      `legacy_allowed: false`, ou seja, o caminho legado já não é usado.

### W4 — Interação de representante (implementada em 2026-08-16)

**Migração `0010`.** `customer_id` vira nulável, entra `actor_user_id` e o
`CHECK` de exatamente um dono. Nenhuma linha existente muda.

Verificada por `tests/test_representative_interactions.py` (12 testes), e
`tests/test_interactions.py` passa sem nenhuma alteração — que é a prova de que
o caminho do cliente, hoje em produção, não mudou de comportamento.

- [x] Aplicar a `0010` contra PostgreSQL — ver "Migrações em produção".
- [ ] **Autorizar o primeiro número de representante no painel do Gateway.**
      Continua sendo o passo que falta, e agora é o único: os executores existem,
      o manifesto anuncia as capacidades e as flags estão ligadas. O log de
      2026-08-22 mostra `actor_role: 'cliente'` — nenhum número de representante
      foi autorizado ainda, então esse caminho **nunca rodou de ponta a ponta**.
- [ ] A reversão da `0010` **falha de propósito** se já houver conversa de
      representante gravada: voltar `customer_id` a `NOT NULL` apagaria o dono
      dessas linhas em silêncio.
- [ ] Q3 agora alcança conteúdo de conversa ligado a **usuário identificado**,
      não só a contato de cliente. O expurgo já cobre as duas, mas o prazo
      continua indefinido.

### W5 — Telas de operação

- [ ] `/portal/whatsapp` — roster, colisões e usuários sem telefone.
- [ ] `/portal/whatsapp/nao-entendidas` — o dado já chega hoje no `payload`.
- [ ] `/portal/whatsapp/vocabulario` — editar aliases e exemplos.

### W6 — Leituras do representante

Sem migração. Rotas em `/internal/representative/by-whatsapp/{phone}/...`,
verificadas por `tests/test_representative_whatsapp.py` (14 testes).

- [x] **Lado do CRM.** As três leituras: artigo em preço-base, clientes da
      carteira e tabela convertida de um cliente da carteira.
- [x] **Lado do Gateway, pedido 1:** adaptador `crm_api` do manifesto canônico,
      cache por ator e resolução determinística genérica (`GW-010`, `GW-012`,
      `GW-013`, `GW-021`). Entregue com as quatro flags desligadas, suíte de lá
      em 96 verde e a baseline de 87 intacta. Os dois manifestos de produção do
      CRM passam pelo `isValidBusinessCapabilityManifest` com o adaptador
      `crm_api` — conferido rodando o validador deles, não por leitura.
- [x] Aliases `produto` e `artigo` de volta ao manifesto do cliente. Não são
      sinônimo de conveniência: eram o comando que o Gateway reconhecia **por
      código** no caminho legado, e no envelope canônico nada fora do manifesto
      reconhece esses termos. Sem eles, `"produto PUE 20"` deixava de resolver por
      regra e passava a depender da LLM.
- [x] Ligar `CRM_CAPABILITY_MANIFEST_ENABLED` e a flag de intenção. **As duas
      estão ligadas em produção**, verificado em 2026-08-22: o caminho canônico
      em `server.js:5197` só é alcançado com ambas, e o log
      `[CRM CAPABILITY MANIFEST RESOLVED]` prova que foi alcançado.
- [x] **Lado do Gateway, pedido 2: os executores.** Feito, e são **quatro**, não
      três — `CRM_REP_SEARCH_PRICE_ITEMS`, `CRM_REP_LOOKUP_CUSTOMER`,
      `CRM_REP_GET_CUSTOMER_PRICE_LIST` e `CRM_REP_CREATE_CUSTOMER_INTAKE`,
      registrados em `server.js:3827`.
- [x] Acrescentar as capacidades ao manifesto do representante. O serviço já
      emite as quatro, incluindo a escrita do pré-cadastro.
- [x] **`legacyAllowed: false`** — o log de produção mostra
      `legacy_allowed: false` na decisão. Não há mais fallback ao caminho legado.

**Achado de 2026-08-22, do log de um "olá":** entre `[MANIFEST DECISION]` e
`[MANIFEST RESOLVED]` passaram-se 3 segundos, e o desfecho foi
`capability_id: 'UNKNOWN', source: 'UNKNOWN'`. É o comportamento correto — uma
saudação não é capacidade nenhuma — mas o custo não é: `server.js:5202` tenta
regra e, falhando, **sempre chama a LLM**. Toda saudação paga uma ida à LLM e
três segundos de espera.

- [ ] Resolver saudação e agradecimento antes da LLM. É o primeiro turno de
      quase toda conversa, e hoje é o mais lento e o mais caro.

Duas decisões de alcance tomadas aqui, mais restritivas que o portal:

- **A carteira é sempre a de quem escreveu, qualquer que seja o papel.** `ADMIN`
  e `MANAGER` veem o tenant inteiro no portal e apenas a própria carteira aqui:
  o canal autentica por número de telefone, prova mais fraca que uma sessão.
- **`whatsapp_icms_enabled` não é consultado** na tabela de um cliente. O
  interruptor existe porque, na tabela do cliente, o número convertido vai direto
  a quem compra; aqui o destinatário é o representante, que é exatamente quem o
  interruptor descreve como capaz de conferir o cálculo. É o caso do portal, em
  outro canal.
- O `calculation_trace` **não** vai na resposta: ele existe para ser conferido
  item a item numa tela.

### W7 — Pré-cadastro de cliente pelo WhatsApp

**Migração `0011`.** Tabela nova, nada existente é alterado. Verificada por
`tests/test_customer_intake.py` (22 testes).

- [x] Tabela `customer_intakes`, com duas guardas no banco: unicidade de
      `(tenant_id, idempotency_key)` — o `wamid` — e o `CHECK` de resolução, que
      amarra cada estado aos seus campos. Aceito tem cliente e não tem motivo;
      rejeitado tem motivo e não tem cliente; pendente não tem nem um nem outro.
- [x] `POST /internal/representative/by-whatsapp/{phone}/customer-intakes`.
      Idempotente: a reentrega devolve `201` com `created: false`.
- [x] Aceitar e rejeitar no serviço, delegando a criação do cliente ao
      `CustomerAdminService` — o mesmo do portal, para que localidade padrão,
      titularidade e auditoria não ganhem uma segunda implementação.
- [x] Aplicar a `0011` contra PostgreSQL — ver "Migrações em produção".
- [x] `/portal/intakes` — fila de pendentes, com revisão, aceite e recusa.
      Representante vê e resolve apenas os que abriu; `ADMIN` e `MANAGER`, a
      fila inteira. O aceite reutiliza `CustomerIntakeService`, preservando o
      titular original e revalidando o telefone antes de autorizar o contato.
- [x] **A máquina de confirmação do Gateway existe e está ligada ao intake.**
      Verificado em 2026-08-22, e corrige o que este item afirmava: `GW-040` a
      `GW-045` não estão todos abertos. `CRM_REP_CREATE_CUSTOMER_INTAKE` está
      registrada como `write` em `server.js:3840`, com coleta de slots, pedido de
      confirmação em `server.js:3987`, tratamento de "sim/não" em `server.js:4088`
      e store em MySQL. O manifesto do representante **já anuncia** a ação.
- [ ] Rodar o pré-cadastro de ponta a ponta pelo WhatsApp. Nada mais bloqueia —
      falta só um número de representante autorizado no painel do Gateway (W4).
- [ ] **Comentário desatualizado no Gateway,** `server.js:3849`: "nenhuma ação
      CRM é de escrita hoje, então a máquina não é instanciada em lugar nenhum".
      O mapa duas linhas acima registra o intake como `write`. O código andou e o
      comentário ficou — e é exatamente o tipo de comentário que faz a próxima
      pessoa concluir que a funcionalidade não existe.

Três invariantes desenhadas de propósito, cada uma com teste que falha se alguém
as afrouxar:

- **Abrir não cria cliente nem autoriza telefone.** O contato só nasce na
  aceitação, no portal. Se a mensagem gravasse o contato direto, uma frase no
  WhatsApp autorizaria um telefone qualquer a conversar com o CRM.
- **O titular é quem abriu, não quem aceitou.** Um `ADMIN` resolvendo a fila no
  escritório não se torna dono da conta.
- **O telefone é revalidado na aceitação.** Entre abrir e aceitar pode passar uma
  semana; sem revalidar, a aceitação criaria a colisão que o manifesto recusa com
  `409` — e o número pararia de ser atendido sem ninguém saber por quê.

## D — Campanhas de WhatsApp / mensagens em lote

Frente documental aberta em 2026-08-31. Substitui o recorte estreito de
"disparo de preço" por campanhas comerciais auditáveis, sem apagar as decisões
úteis: produto/grupo, aviso de queda e confirmação humana continuam casos da
mesma capacidade. Especificação: [Campanhas de WhatsApp](../10_product/WHATSAPP_CAMPAIGNS.md).
Plano de entrega faseado, registrado em 2026-09-02:
[F6](../40_delivery/F6_WHATSAPP_CAMPAIGNS.md) — F6.1/F6.2 podem começar sem
integração externa; F6.4 (Gateway) só depois de F6.0 fechada.

### D0 — Limites já fechados

- [x] CRM resolve carteira, público e autorização; Gateway é dono da Meta,
      templates operacionais, consentimento/opt-out, envio e estados do canal.
- [x] `REPRESENTATIVE` só alcança clientes da própria carteira; `ADMIN` e
      `MANAGER` acompanham o tenant inteiro.
- [x] `product_groups`, e não `product_families`, é o eixo de produto. Fibra e
      composição podem compor critérios, sem inferir classificação ausente.
- [x] Toda escrita exige confirmação explícita, revalidação de autorização,
      idempotência e auditoria.
- [x] Consentimento é obrigatório e deve ser reavaliado pelo Gateway antes de
      cada envio; marketing fora de 24 horas usa template Meta.

### D1 — Base de segmentação

- [x] `product_groups` e `product_group_members` implementados na migração
      `0013`; são N↔N e do tenant. Família continua sendo layout da tabela.
- [x] `fibers` e `product_compositions` implementados na migração `0014`; item
      sem composição é não classificado, nunca negativa implícita.
- [ ] Aplicar a `0013` e `0014` no PostgreSQL e confirmar nos logs de start.
- [ ] Implementar filtro de carteira por grupo e por composição/produto
      preferencial, sempre sob escopo do representante.
- [ ] Confirmar se “preferido” significa sinal de compra para segmentação; hoje
      ele seleciona o que entra na tabela do cliente.
- [ ] Modelar porte como atributo declarado em eixo exclusivo (`eixo + valor`),
      com unicidade por cliente e eixo; não inferir de dados inexistentes.
- [ ] Modelar lista de julgamento não exclusiva, com dono e visibilidade.
- [ ] Decidir se listas de julgamento são privadas por representante ou visíveis
      no tenant; não há resposta técnica segura por padrão.
- [ ] Criar operação de mesclagem e etiquetagem em lote de grupos, para evitar
      taxonomia duplicada e classificação manual inviável.

### D2 — Agregado comercial e prévia no CRM

- [ ] Modelar campanha, destinatário, critérios/template/variáveis congelados,
      referência externa do Gateway e auditoria, conforme o modelo-alvo.
- [ ] Implementar prévia determinística: elegíveis, sem contato, sem dado para
      o critério e exclusões de consentimento retornadas pelo Gateway.
- [ ] Criar rascunho idempotente e confirmar apenas depois de revisão explícita.
- [ ] Exigir revisão nominal no portal acima do limite configurável — **350
      destinatários**, ADR-029; abaixo dele, permitir confirmação
      conversacional somente após executor validado.
- [ ] Implementar cancelamento que afete apenas rascunho/não iniciado/pendente,
      preservando o que já ocorreu no canal.
- [ ] Definir retenção LGPD para snapshots de campanha e sua relação com o
      expurgo das interações; nenhuma limpeza recebe prazo padrão.

### D3 — Contratos e execução no Gateway

- [ ] Fechar ADR de comandos CRM → Gateway e eventos Gateway → CRM, com HMAC,
      correlação, idempotência, replay, tentativa parcial e reconciliação.
- [ ] Implementar catálogo operacional dos templates Meta permitidos e validação
      de variáveis; o CRM não cria template.
- [ ] Implementar prévia e revalidação imediatamente anterior ao envio de
      consentimento/opt-out no Gateway.
- [ ] Implementar fila, rate limit, estado por destinatário e cancelamento de
      pendências no Gateway, sem bloquear webhooks existentes.
- [ ] Emitir ao CRM eventos idempotentes de campanha, destinatário, mensagem,
      estado (`PENDING`, `SENT`, `DELIVERED`, `READ`, `FAILED`) e resposta.
- [ ] Confirmar no repositório do Gateway o plano e módulo de campanhas: eles
      não existem na cópia local analisada neste repositório.

### D4 — Portal e ficha do cliente

- [ ] Listar campanhas por período, situação, representante, template e
      segmentos, aplicando escopo de carteira no repositório.
- [ ] Exibir detalhe com destinatários, exclusão por falta de consentimento,
      resultados, pedido, filtros, template, variáveis e confirmação.
- [ ] Ligar campanha e destinatário à ficha/timeline do cliente, incluindo
      mensagem e resposta relacionadas.
- [ ] Medir e apresentar limitações/erros operacionais sem apresentar a projeção
      do CRM como fonte de verdade do canal.

### D5 — Manifesto conversacional, após executor

- [ ] Definir slots, vocabulário, allowlist e fixture de contrato para
      `CRM_PREVIEW_WHATSAPP_CAMPAIGN_AUDIENCE`.
- [ ] Definir os mesmos artefatos para criar, confirmar, cancelar e consultar:
      `CRM_CREATE_WHATSAPP_CAMPAIGN_DRAFT`,
      `CRM_CONFIRM_WHATSAPP_CAMPAIGN`,
      `CRM_CANCEL_WHATSAPP_CAMPAIGN` e
      `CRM_GET_WHATSAPP_CAMPAIGN_STATUS`.
- [ ] Reconciliar as intenções históricas `BROADCAST_OFERTA`,
      `COMUNICAR_DISPONIBILIDADE_E_PRECO`, `GERAR_LISTA_PROSPECCAO`,
      `REGISTRAR_INTERESSE` e `CONSULTAR_HISTORICO_CLIENTE` conforme o
      mapeamento documental; não publicar capability sem executor local.

### D6 — Casos comerciais a preservar

- [ ] Detector de queda de preço: `price_entry_revisions` já permite comparar
      `previous` e `current` por lote; falta definir piso e frequência máxima.
- [ ] Aviso de queda deve cruzar grupo com clientes que preferem artigo que caiu,
      não avisar todo o grupo indistintamente.
- [ ] O template, idioma, variáveis e eventual fluxo de resposta do aviso de
      queda são decisões comerciais e operacionais do Gateway, não texto livre
      criado pelo CRM.

## Pendências herdadas

- [ ] Implementar idempotência por `event_id`.
- [ ] Criar testes de integração com PostgreSQL.
- [ ] Consulta específica de item por SKU, nome comercial, especificação ou família.
- [x] Validar em produção o manifesto de capacidades por sessão no `crm_api` —
      verificado em 2026-08-22 pelo log de um "olá": manifesto servido,
      `actor_role: 'cliente'`, `capability_count: 2`.
- [ ] Coerência de `tenant_id` entre todas as FKs.
- [ ] Migrar `conversations`, `messages`, `inbound_events` e `outbound_messages` ao Gateway.

## Concluído

- [x] Definir stack e versão do runtime.
- [x] Criar configuração local e para CapRover.
- [x] Aplicar migrações PostgreSQL no ambiente CapRover.
- [x] Implementar autenticação interna por HMAC.
- [x] Executar, revisar e ativar a importação manual da tabela especial de 20/07/2026.
- [x] Implementar a consulta interna da tabela vigente por contato WhatsApp.
- [x] Adicionar ordenação explícita de item de tabela (`0002`).
- [x] Integrar o comando `tabela` no Gateway compartilhado.

## Congelado pelo ADR-013

Os itens `MC-001` a `MC-007` do backlog de representante multiempresa. O
documento permanece como referência histórica.

## Fora do MVP

- Leitura automática de PDF em produção.
- Oferta, negociação autônoma e envio sem aprovação humana.
- Substituição tributária, DIFAL, redução de base e Simples Nacional.
- Frete determinístico.
- Exceções comerciais criadas pela LLM.
