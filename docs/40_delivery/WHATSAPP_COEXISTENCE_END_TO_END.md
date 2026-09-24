# WhatsApp Coexistence — jornada ponta a ponta CRM ↔ Gateway

**Estado:** vertical slice implementado e validado em ambiente real.  
**Escopo:** onboarding e a validação básica de coexistência. Este documento é a fonte canônica para esse recorte; não torna a conversa híbrida completa, campanhas pelo novo vínculo ou F7 concluídos.

## O que está implementado e validado

- Um representante conectado no CRM conclui o onboarding pelo portal e passa a ver o número em `CONNECTED`.
- A linha foi usada em coexistência: inbound de cliente chegou ao Gateway e foi roteado para `crm_textil` / `consulta_cliente`; houve resposta automática e resposta manual pelo WhatsApp Business App no mesmo número.
- O Gateway observou `smb_message_echoes` para a resposta manual.

Isso comprova o vertical slice de Coexistence e a viabilidade básica do Plano A: o WhatsApp Business App e o canal operado pelo Gateway coexistem na identidade do representante. Não comprova, por si só, a automação de campanhas nem a orquestração completa humano + bot.

> A evidência atual valida um vertical slice ponta a ponta em ambiente real. Não constitui validação de escala, carga, múltiplos representantes simultâneos, failover ou cobertura multi-tenant ampla.

## Jornada do usuário

```text
Representante (ou ADMIN/MANAGER do mesmo tenant)
  → ficha/tela WhatsApp Business → Conectar WhatsApp
  → CRM cria RepresentativeWhatsappConnection e onboarding no Gateway
  → CRM recebe launch_url e abre popup
  → usuário conclui Meta Embedded Signup
  → CRM faz polling do status sanitizado do Gateway
  → Gateway COMPLETED → CRM CONNECTED → número exibido
```

- `REPRESENTATIVE` opera apenas a própria conexão. `ADMIN` e `MANAGER` podem operar conexões do mesmo tenant; não atravessam tenant.
- O popup só é aberto se houver `launch_url`. Um `resume` pode continuar apenas no servidor, sem popup; o polling segue a cada três segundos por até cinco minutos, ou até estado terminal.
- O CRM apresenta `CONNECTING`, `CONNECTED`, `ACTION_REQUIRED`, `CONFLICT` e `FAILED`, com uma ação de recuperação calculada no servidor. A UI não interpreta `failure_code`.
- Em `RESTART`, a nova tentativa pertence ao mesmo representante. A tentativa `FAILED` anterior permanece no histórico: não se cria usuário nem se altera e-mail ou telefone para reiniciar.

## Limite de responsabilidades

| CRM | Gateway — não pertence ao CRM |
|---|---|
| tenant, representante, RBAC e vínculo comercial | OAuth Meta, tokens e credenciais |
| `RepresentativeWhatsappConnection`, idempotência e auditoria | WABA, `phone_number_id` e `subscribed_apps` |
| UX, popup, polling e projeção sanitizada de status | Embedded Signup, `launch_url`, provisioning e `whatsapp_lines` |
| histórico das tentativas e número exibível | `line_flow_bindings`, webhook, roteamento e transporte Meta |

O CRM não chama a Graph API, não persiste token Meta, código OAuth, segredo, payload bruto de webhook ou `launch_url`. A referência de linha do Gateway é correlação técnica; a autoridade operacional permanece no Gateway.

## Contrato CRM → Gateway usado no onboarding

O cliente interno do CRM chama o Gateway com Bearer token server-side, timeout e chave de idempotência. As respostas são validadas e sanitizadas antes da projeção.

| Operação | Finalidade | Resultado relevante para o CRM |
|---|---|---|
| `create` | inicia onboarding com referências de tenant e representante | `onboarding_id`, estado, `launch_url` temporária |
| `GET status` | atualiza a tentativa em andamento | estado, `display_phone_number`, referência de linha e falha sanitizada |
| `resume` | retoma trabalho técnico recuperável | estado e, opcionalmente, nova `launch_url` |

O contrato concreto atualmente usado pelo CRM é `POST /internal/meta/whatsapp/onboardings`, `GET /internal/meta/whatsapp/onboardings/{onboarding_id}` e `POST /internal/meta/whatsapp/onboardings/{onboarding_id}/resume`. O `create` informa `application_reference=crm_textil` e `flow_reference=consulta_cliente`; a resolução e o vínculo técnico continuam no Gateway.

## Mapeamento de estado Gateway → CRM

| Gateway | CRM | Experiência |
|---|---|---|
| `AUTHORIZATION_PENDING`, `TOKEN_EXCHANGE_PENDING`, `TOKEN_RECEIVED`, `ASSET_DISCOVERY_PENDING`, `ASSET_DISCOVERED`, `PROVISIONING` | `CONNECTING` | aguardar/polling |
| `COMPLETED` | `CONNECTED` | mostrar `display_phone_number` quando fornecido |
| `ACTION_REQUIRED` | `ACTION_REQUIRED` | orientar retomada autorizada |
| `CONFLICT` | `CONFLICT` | informar conflito sem expor diagnóstico sensível |
| `FAILED` | `FAILED` | mostrar ação de recuperação calculada |

`NOT_CONNECTED` é o estado de ausência de tentativa projetado pelo CRM, não uma conclusão técnica substituta do Gateway.

`SUBSCRIPTION_PENDING` é mantido pelo CRM como mapeamento defensivo/reservado para `CONNECTING`, caso seja recebido do Gateway. Não é apresentado aqui como transição pública efetiva do lifecycle de onboarding; a autoridade para expô-lo ou não permanece no Gateway.

## Retry e nova autorização

| Situação | Ação CRM | Efeito |
|---|---|---|
| falha recuperável, por exemplo `TRANSIENT_GATEWAY_FAILURE` | `RESUME` | retoma o mesmo onboarding; pode não haver popup |
| `TOKEN_EXCHANGE_REJECTED` | `RESTART` | cria novo onboarding e nova chave de idempotência; conserva o histórico falho |
| `NEW_AUTHORIZATION_REQUIRED` | `RESTART` | inicia nova autorização Meta para o mesmo representante |
| `ACTION_REQUIRED` | `RESUME` | solicita continuidade ao Gateway; há popup apenas se ele devolver URL |

Uma tentativa ativa por tenant/representante é permitida (`CONNECTING`, `CONNECTED` ou `ACTION_REQUIRED`). `CONFLICT` e falhas não recuperáveis não são convertidos silenciosamente em conexão ativa.

## Configuração do CRM

Configurar sem registrar valores secretos em documentos, logs ou auditoria:

- `CRM_WHATSAPP_GATEWAY_BASE_URL`
- `CRM_WHATSAPP_GATEWAY_INTERNAL_TOKEN`
- `CRM_WHATSAPP_GATEWAY_TIMEOUT_SECONDS`

O token é exclusivamente server-side e corresponde ao mecanismo interno acordado com o Gateway. A alteração exige a migração e reinício usuais do CRM, conforme o procedimento operacional do ambiente.

## Fluxo validado após a conexão

```text
Cliente → Gateway → crm_textil / consulta_cliente → resposta automática
Representante → WhatsApp Business App → mesmo número → cliente
                                      └→ smb_message_echoes observado no Gateway
```

Portanto, inbound, automação já configurada no Gateway e intervenção humana manual foram observados na mesma identidade WhatsApp Business. O dado não deve ser extrapolado para afirmar que o CRM já possui timeline unificada, detecção/projeção completa de autoria ou supressão de bot.

## Implementado, parcial e futuro

| Classificação | Escopo |
|---|---|
| **Implementado e validado** | onboarding CRM ↔ Gateway, RBAC por tenant, vínculo e histórico de tentativas, popup/polling/status, `CONNECTED` com número, inbound roteado, resposta automática, resposta humana no App e `smb_message_echoes` observado no Gateway. |
| **Implementado mas ainda parcial** | CRM projeta estados e dados sanitizados da conexão; a integração de onboarding não substitui callback em tempo real, troubleshooting avançado, desconexão/remoção ou múltiplas linhas. A observação de echo ainda não significa projeção de conversa no CRM. |
| **Futuro** | timeline única `CUSTOMER`/`HUMAN`/`BOT`/`SYSTEM`; máquina real `HUMAN_ACTIVE`/`BOT_ACTIVE`/`WAITING_HUMAN`/`BOT_ASSIST`; supressão automática do bot ao detectar humano; handoff e reassunção; reconstrução histórica integral; automação de campanhas usando o novo vínculo. |

## Referências e histórico

- [Onboarding operacional](WHATSAPP_COEXISTENCE_ONBOARDING.md) resume a entrega CRM.
- [Arquitetura de Coexistence](../30_architecture/WHATSAPP_REPRESENTATIVE_COEXISTENCE.md) separa a evidência validada da arquitetura futura de conversa híbrida.
- [F7 — conversa híbrida](F7_WHATSAPP_HYBRID_CONVERSATION.md) continua sendo planejamento futuro.
- As hipóteses e o roteiro da PoC original foram preservados como histórico na [fonte Plano A / Plano B](../90_references/CRM_TEXTIL_FONTE_PLANO_A_B_WHATSAPP.md).
