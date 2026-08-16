# Backlog priorizado

Direção vigente: [CRM de representantes](../10_product/REPRESENTATIVE_DIRECTION.md).
Plano de entrega: [F5](../40_delivery/F5_REPRESENTATIVE_PORTAL.md).

## P0 — Decisões que bloqueiam implementação

- [ ] Confirmar se o preço-base carregado já contém ICMS embutido e qual alíquota (Q1).
- [ ] Confirmar a fórmula de conversão entre UFs: "por dentro" ou acréscimo simples (Q2).
- [ ] Definir retenção e visibilidade do histórico de interações sob LGPD (Q3).
- [x] Q4 — a interface é server-rendered na mesma origem da API (ADR-017).

Q1 e Q2 bloqueavam R4, que foi implementada assim mesmo com fórmula selecionável
e sem estimativa implícita; a confirmação continua obrigatória antes de qualquer
preço convertido chegar a um cliente.

Q3 não bloqueou R5. O que ela decide é o **prazo** de retenção, e enquanto não
houver decisão o sistema não apaga nada: o expurgo recusa rodar sem política.

## R0 — Fundação de identidade (implementada)

- [x] Migração `0003`: `users`, `user_sessions`, `audit_log`, enum `user_role`.
- [x] Hash Argon2id, política de senha e bloqueio por tentativas.
- [x] Sessão segura, revogada ao desativar o usuário e no logout.
- [x] Autorização por papel, separada do HMAC do Gateway.
- [x] Rate limit no login.
- [x] Seed do primeiro `ADMIN` sem SQL manual (`crm_api.admin_cli`).
- [ ] Aplicar a migração `0003` contra PostgreSQL e conferir o resultado.
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
- [ ] Carga CSV inicial da matriz das 27 UFs.
- [ ] **Confirmar Q1/Q2 antes de qualquer preço ir a cliente.**

## R5 — Histórico de interações (implementada)

- [x] Migração `0008`: `customer_interactions` e enum `interaction_direction`.
- [x] `POST /internal/interactions` idempotente por `(tenant, source, external_ref)`.
- [x] Timeline paginada por cliente, com escopo de carteira.
- [x] Rotina de expurgo auditada, que recusa rodar sem política definida.
- [x] Filtro de carteira por última interação — desbloqueia o pendente de R1.
- [ ] **Push assíncrono no Gateway**, com retry e sem bloquear a resposta ao
      contato. Outro repositório; contrato em
      [F5_INTERACTION_PUSH_CONTRACT](../40_delivery/F5_INTERACTION_PUSH_CONTRACT.md).
- [ ] Definir Q3 e configurar `CRM_INTERACTION_RETENTION_DAYS`.
- [ ] Agendar a execução periódica do expurgo.

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

- [ ] Aplicar a `0009` contra PostgreSQL. **A migração para se encontrar um
      telefone que seja usuário do portal e contato de cliente ao mesmo tempo** —
      resolver a colisão é decisão comercial, não do script.
- [ ] Agendar `python -m crm_api.admin_cli check-whatsapp-identities`.

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

- [ ] Publicar antes de o Gateway ligar a flag — o CRM precisa estar no ar
      primeiro, como foi no piloto do manifesto legado.
- [ ] Quando a flag virar lá, congelar o `GET /internal/interaction-capabilities`.

### W4 — Interação de representante (implementada em 2026-08-16)

**Migração `0010`.** `customer_id` vira nulável, entra `actor_user_id` e o
`CHECK` de exatamente um dono. Nenhuma linha existente muda.

Verificada por `tests/test_representative_interactions.py` (12 testes), e
`tests/test_interactions.py` passa sem nenhuma alteração — que é a prova de que
o caminho do cliente, hoje em produção, não mudou de comportamento.

- [ ] Aplicar a `0010` contra PostgreSQL.
- [ ] **Já pode autorizar o primeiro número de representante no painel do
      Gateway.** Era esta etapa que faltava.
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

- [ ] Busca de artigo em preço-base, localizar cliente da carteira e tabela de
      cliente da carteira. Três executores novos no Gateway.

### W7 — Pré-cadastro de cliente pelo WhatsApp

- [ ] Tabela `customer_intakes`, endpoint de escrita e fila `/portal/intake`.
- [ ] **Depende da máquina de confirmação do Gateway** (`GW-040` a `GW-045`,
      todos abertos). É a última etapa a funcionar, não a primeira.

## Pendências herdadas

- [ ] Implementar idempotência por `event_id`.
- [ ] Criar testes de integração com PostgreSQL.
- [ ] Consulta específica de item por SKU, nome comercial, especificação ou família.
- [ ] Validar em produção o manifesto de capacidades por sessão no `crm_api`.
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
