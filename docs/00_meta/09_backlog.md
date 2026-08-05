# Backlog priorizado

Direção vigente: [CRM de representantes](../10_product/REPRESENTATIVE_DIRECTION.md).
Plano de entrega: [F5](../40_delivery/F5_REPRESENTATIVE_PORTAL.md).

## P0 — Decisões que bloqueiam implementação

- [ ] Confirmar se o preço-base carregado já contém ICMS embutido e qual alíquota (Q1).
- [ ] Confirmar a fórmula de conversão entre UFs: "por dentro" ou acréscimo simples (Q2).
- [ ] Definir retenção e visibilidade do histórico de interações sob LGPD (Q3).
- [ ] Decidir onde vive a interface do portal (Q4) — antes de R6, não antes de R0.

Q1 e Q2 bloqueiam R4. As demais não bloqueiam o início.

## R0 — Fundação de identidade (implementada)

- [x] Migração `0003`: `users`, `user_sessions`, `audit_log`, enum `user_role`.
- [x] Hash Argon2id, política de senha e bloqueio por tentativas.
- [x] Sessão segura, revogada ao desativar o usuário e no logout.
- [x] Autorização por papel, separada do HMAC do Gateway.
- [x] Rate limit no login.
- [x] Seed do primeiro `ADMIN` sem SQL manual (`crm_api.admin_cli`).
- [ ] Aplicar a migração `0003` contra PostgreSQL e conferir o resultado.
- [ ] Substituir o limitador em processo caso o serviço passe a rodar replicado.

## P0 — R1 Representante e carteira (próxima)

- [ ] Migração `0004`: `customers.owner_user_id`, `customer_assignment_history`.
- [ ] CRUD de representantes.
- [ ] Designação e transferência de titular com motivo e histórico.
- [ ] `GET /admin/me/customers` e `GET /admin/customers` com escopo por papel.
- [ ] Teste de isolamento de carteira na camada de repositório.

## P0 — R3 Preço por competência

- [ ] Migração `0006`: `price_entries`, `price_entry_revisions`, status `PUBLISHED`.
- [ ] Publicação de lote com `UPSERT` transacional e revisão por linha.
- [ ] Importação CSV com prévia e relatório de divergências antes de gravar.
- [ ] Backfill da tabela ativa de 20/07/2026 para a competência `2026-07`.
- [ ] Teste de contrato antes/depois nas rotas consumidas pelo Gateway.

## P1 — R2 Localidades

- [ ] Migração `0005`: `customer_locations` e backfill da UF atual.
- [ ] CRUD de localidades com unicidade da padrão ativa.
- [ ] Validação de UF contra as 27 unidades federativas.

## P1 — R4 Motor de ICMS

- [ ] Migração `0007`: `tenants.origin_state_code`, `icms_rules`, depreciar `tax_rules`.
- [ ] Resolução determinística por especificidade, com erro em empate e em ausência.
- [ ] Conversão de preço com `calculation_trace` auditável.
- [ ] Rota de lista personalizada por cliente, localidade e competência.
- [ ] Carga CSV inicial da matriz das 27 UFs.

## P1 — R5 Histórico de interações

- [ ] Migração `0008`: `customer_interactions`.
- [ ] `POST /internal/interactions` idempotente por `(source, external_ref)`.
- [ ] Push assíncrono no Gateway, com retry e sem bloquear a resposta ao contato.
- [ ] Timeline paginada por cliente, com escopo de carteira.
- [ ] Rotina de expurgo auditada.

## P2 — R6 Portal

- [ ] Tela de carteira.
- [ ] Ficha do cliente com localidades, preferências, timeline e tabela resolvida.
- [ ] Tela da tabela do mês: importar, revisar, publicar, histórico de revisões.
- [ ] Tela da matriz de ICMS.
- [ ] Tela de representantes e transferência de carteira.

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
