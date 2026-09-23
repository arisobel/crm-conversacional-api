# Onboarding WhatsApp Coexistence — CRM

**Estado:** implementado no CRM em 2026-09-23; requer Gateway compatível configurado para funcionar ponta a ponta.

## Fluxo

```text
Representative UI → CRM route → CRM service → Gateway client
→ Gateway onboarding → Embedded Signup → Gateway provisioning
→ CRM polling → CONNECTED
```

O CRM é dono de tenant, usuário, RBAC, vínculo comercial, UX e auditoria. O Gateway é dono de Embedded Signup, OAuth, token, WABA, `phone_number_id`, linha, routing e webhook.

## Entrega

- Migração `0016_whatsapp_onboarding` e `RepresentativeWhatsappConnection`.
- Uma conexão ativa (`CONNECTING`, `CONNECTED` ou `ACTION_REQUIRED`) por tenant/representante.
- Cliente privado com Bearer token server-side, timeout e resposta sanitizada.
- API de sessão: `POST`/`GET /api/v1/representatives/{user_id}/whatsapp-connection` e `POST .../resume`.
- Representante acessa somente a própria conexão; `ADMIN` e `MANAGER` operam somente o mesmo tenant.
- Popup somente quando o Gateway retornar `launch_url`; um resume sem URL continua server-side e o polling segue a cada três segundos, no máximo cinco minutos, até estado terminal.
- Auditoria de início, conclusão, falha, conflito, ação requerida e retomada, sem URLs ou segredos.

## Estados

`AUTHORIZATION_PENDING`, `TOKEN_EXCHANGE_PENDING`, `TOKEN_RECEIVED`, `ASSET_DISCOVERY_PENDING`, `ASSET_DISCOVERED`, `SUBSCRIPTION_PENDING` e `PROVISIONING` projetam `CONNECTING`. `COMPLETED` projeta `CONNECTED`; `ACTION_REQUIRED`, `CONFLICT` e `FAILED` preservam seus estados comerciais.

## Deploy e teste manual

Configurar `CRM_WHATSAPP_GATEWAY_BASE_URL`, `CRM_WHATSAPP_GATEWAY_INTERNAL_TOKEN` (igual a `INTERNAL_STATUS_API_TOKEN` do Gateway) e `CRM_WHATSAPP_GATEWAY_TIMEOUT_SECONDS`; aplicar `alembic upgrade head`; reiniciar o CRM.

Como representante, abrir **WhatsApp Business**, clicar **Conectar WhatsApp**, concluir Embedded Signup na janela e aguardar `CONNECTED` e o número. Isso não exige curl, SQL, token manual ou painel técnico do Gateway.
