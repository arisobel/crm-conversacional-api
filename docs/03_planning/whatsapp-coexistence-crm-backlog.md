# Backlog — onboarding WhatsApp Coexistence no CRM

**Natureza:** registro de planejamento e pendências remanescentes.
**Estado:** P0 implementado e validado ponta a ponta; a especificação vigente é [WhatsApp Coexistence — jornada ponta a ponta CRM ↔ Gateway](../40_delivery/WHATSAPP_COEXISTENCE_END_TO_END.md).

## P0 concluído e validado

O CRM já permite a um representante — ou `ADMIN`/`MANAGER` do mesmo tenant — abrir a tela WhatsApp Business, iniciar a conexão, concluir Embedded Signup em popup, acompanhar polling e ver o número em `CONNECTED`.

O CRM criou `RepresentativeWhatsappConnection`, aplicou RBAC, projetou estado sanitizado e registrou auditoria/histórico de tentativas. `RESUME` reaproveita onboarding recuperável; `RESTART` cria uma tentativa nova para o mesmo representante, mantendo a falha anterior no histórico. O CRM não manipula token, WABA, `phone_number_id` ou URL técnica fora da jornada.

A validação real também cobriu, após conexão, inbound roteado pelo Gateway para `crm_textil / consulta_cliente`, resposta automática, resposta manual pelo WhatsApp Business App no mesmo número e `smb_message_echoes` observado no Gateway.

## Fronteira de responsabilidade preservada

| CRM | Gateway |
|---|---|
| tenant, representante, RBAC, vínculo comercial, UX, auditoria e projeção de estado | Embedded Signup, OAuth Meta, token, WABA, `phone_number_id`, `subscribed_apps`, linha, `line_flow_bindings`, webhook e routing |

O CRM nunca persiste token Meta, App Secret, código OAuth, payload de webhook ou `launch_url`; não chama a Graph API nem usa banco do Gateway.

## Itens ainda abertos

1. Callback interno Gateway → CRM para complementar/substituir polling, reconciliação e troubleshooting operacional.
2. Desconectar/remover, linha degradada, substituição e regras de múltiplas linhas por representante.
3. Política de mascaramento do número, diagnóstico por perfil e retenção LGPD da projeção de conexão.
4. Contrato de campanhas F6.4: sender pela linha vinculada, templates, consentimento, eventos e status. A validação básica de Coexistence não conclui automação de campanhas.
5. F7: timeline única, autoria completa, estados `HUMAN_ACTIVE`/`BOT_ACTIVE`/`WAITING_HUMAN`/`BOT_ASSIST`, supressão automática do bot, handoff, reassunção e reconstrução histórica.

## Histórico convertido

Os épicos C1–C8 e o gate da PoC básica eram o plano que levou ao P0 agora validado; foram substituídos por este registro de resultado para não parecerem trabalho pendente. C9/C10 foram reclassificados acima como trabalho futuro. O roteiro detalhado da PoC permanece arquivado na [fonte Plano A / Plano B](../90_references/CRM_TEXTIL_FONTE_PLANO_A_B_WHATSAPP.md).
