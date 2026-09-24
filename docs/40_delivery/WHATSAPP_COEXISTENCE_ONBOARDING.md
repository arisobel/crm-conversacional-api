# Onboarding WhatsApp Coexistence — CRM

**Estado:** implementado e validado ponta a ponta. A referência canônica, incluindo evidência de coexistência, é [WhatsApp Coexistence — jornada ponta a ponta CRM ↔ Gateway](WHATSAPP_COEXISTENCE_END_TO_END.md).

## Resumo operacional

```text
Representative UI → CRM route → CRM service → Gateway client
→ Gateway onboarding → Embedded Signup → Gateway provisioning
→ CRM polling → CONNECTED
```

O CRM é dono de tenant, usuário, RBAC, vínculo comercial, UX e auditoria. O Gateway é dono de Embedded Signup, OAuth, token, WABA, `phone_number_id`, linha, routing e webhook. A validação real incluiu inbound roteado a `crm_textil / consulta_cliente`, resposta automática, resposta manual no WhatsApp Business App e `smb_message_echoes` observado no Gateway.

## Entrega implementada

- Migração `0016_whatsapp_onboarding` e `RepresentativeWhatsappConnection`.
- Uma conexão ativa (`CONNECTING`, `CONNECTED` ou `ACTION_REQUIRED`) por tenant/representante.
- Cliente privado com Bearer token server-side, timeout e resposta sanitizada. O CRM gera, persiste e reutiliza a `idempotency_key`; o Gateway valida/enforce o onboarding idempotente (mesma chave + mesmo corpo reutiliza onboarding; mesma chave + corpo diferente conflita).
- API de sessão: `POST`/`GET /api/v1/representatives/{user_id}/whatsapp-connection` e `POST .../resume`.
- Representante acessa somente a própria conexão; `ADMIN` e `MANAGER` operam somente o mesmo tenant.
- Popup somente quando o Gateway retornar `launch_url` no início do onboarding. `resume` é essencialmente server-side e normalmente não retorna nova URL; o CRM aceita uma URL opcional apenas por compatibilidade/defesa. Se a Meta exigir nova interação, a ação apropriada é `RESTART`/novo onboarding. O polling segue a cada três segundos, no máximo cinco minutos, até estado terminal.
- Auditoria de início, conclusão, falha, conflito, ação requerida e retomada, sem URLs ou segredos.

## Estados e retry

`AUTHORIZATION_PENDING`, `TOKEN_EXCHANGE_PENDING`, `TOKEN_RECEIVED`, `ASSET_DISCOVERY_PENDING`, `ASSET_DISCOVERED` e `PROVISIONING` projetam `CONNECTING`. `COMPLETED` projeta `CONNECTED`; `ACTION_REQUIRED`, `CONFLICT` e `FAILED` preservam seus estados comerciais. `SUBSCRIPTION_PENDING`, se recebido, também é projetado defensivamente para `CONNECTING`, mas é estado interno/reservado do Gateway e não transição pública efetiva declarada por este lifecycle.

O CRM calcula `retry_action` e a interface não interpreta `failure_code` diretamente. `TOKEN_EXCHANGE_REJECTED` e `NEW_AUTHORIZATION_REQUIRED` exigem `RESTART`; falhas recuperáveis usam `RESUME`. O restart cria novo onboarding e chave de idempotência para o mesmo representante, preservando a tentativa anterior no histórico. Só uma tentativa ativa continua permitida por representante.

No `create` atual, `customer_reference = tenant_reference`: trata-se da referência externa do tenant/conta comercial usada como contexto do onboarding, não necessariamente de um customer/cliente comercial do CRM. `representative_reference = representative.public_ref`; tenant, customer comercial e representante são conceitos distintos.

## Deploy e teste manual

Configurar `CRM_WHATSAPP_GATEWAY_BASE_URL`, `CRM_WHATSAPP_GATEWAY_INTERNAL_TOKEN` (igual a `INTERNAL_STATUS_API_TOKEN` do Gateway) e `CRM_WHATSAPP_GATEWAY_TIMEOUT_SECONDS`; aplicar `alembic upgrade head`; reiniciar o CRM.

Como representante, abrir **WhatsApp Business**, clicar **Conectar WhatsApp**, concluir Embedded Signup na janela e aguardar `CONNECTED` e o número. Isso não exige curl, SQL, token manual ou painel técnico do Gateway.
