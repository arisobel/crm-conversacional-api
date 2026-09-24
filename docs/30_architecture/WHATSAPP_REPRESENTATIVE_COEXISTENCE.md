# WhatsApp Coexistence e conversa híbrida do representante

**Natureza:** arquitetura de fronteira e evolução do Plano A.
**Estado:** o vertical slice de Coexistence está implementado e validado; a conversa híbrida completa permanece arquitetura futura.

A evidência e o contrato de onboarding estão consolidados em [WhatsApp Coexistence — jornada ponta a ponta CRM ↔ Gateway](../40_delivery/WHATSAPP_COEXISTENCE_END_TO_END.md). Este documento não substitui aquele contrato e não declara F6.4, F7, campanhas pelo vínculo ou automação humano + bot como entregues.

## Evidência atual e seu limite

Foi validado um número conectado pelo CRM, inbound de cliente roteado pelo Gateway para `crm_textil / consulta_cliente`, resposta automática, resposta manual pelo WhatsApp Business App no mesmo número e `smb_message_echoes` observado no Gateway. Assim, a coexistência básica App + Gateway e o núcleo técnico do Plano A deixaram de ser hipótese/PoC pendente.

Ainda não há evidência de produto para timeline única no CRM, autoria projetada integralmente, máquina de modos, bloqueio automático de bot, handoff, reassunção, reconstrução histórica ou campanhas automatizadas por esse vínculo. Essas frentes não podem ser inferidas da validação básica.

## Autoridades

| CRM-api | Gateway |
|---|---|
| tenant, representante, cliente, carteira, RBAC, regras comerciais e auditoria | Meta Cloud API, OAuth, tokens, WABA, `phone_number_id`, linha, sender, webhook e transporte |
| vínculo comercial e projeção histórica/sanitizada | `whatsapp_lines`, `line_flow_bindings`, eventos de canal e estado operacional imediato |
| informação autorizada para o cliente | detecção técnica de mensagem manual e decisão imediata de envio/supressão quando isso existir |

O CRM não chama a Meta nem armazena credenciais. A identidade comercial do representante não é a identidade técnica de canal: o CRM a autoriza; o Gateway resolve a linha autorizada.

## Plano A e Plano B

Plano A segue preferencial: o Gateway pode operar a linha WhatsApp Business vinculada ao representante, preservando a relação direta representante ↔ cliente. A validação básica torna esse caminho tecnicamente viável, mas não implementa ainda o sender de campanhas ou seu contrato F6.4.

Plano B, pela WABA central, continua fallback explícito. Uma falha para resolver uma linha do representante nunca deve cair silenciosamente para a linha central: qualquer fallback precisa de decisão, configuração e auditoria.

## Conversa híbrida — alvo futuro

Os estados abaixo são candidatos de F7, não uma máquina de estados existente:

| Estado candidato | Significado pretendido |
|---|---|
| `HUMAN_ACTIVE` | representante conduz a conversa |
| `BOT_ACTIVE` | automação pode responder conforme política |
| `WAITING_HUMAN` | automação aguarda intervenção humana |
| `BOT_ASSIST` | IA auxilia sem enviar ao cliente |

O princípio desejado é que uma mensagem manual prevaleça sobre automação. Embora `smb_message_echoes` já tenha sido observado no Gateway, ainda não há implementação que projete a autoria no CRM, mude esses estados, cancele resposta pendente ou suprima automaticamente o bot.

Da mesma forma, `CUSTOMER`, `HUMAN`, `BOT` e `SYSTEM` são autoria-alvo para uma futura timeline unificada, não dados completos já reconstruídos no CRM.

## Invariantes preservadas

1. CRM-api não chama a Meta diretamente.
2. Gateway não decide carteira ou regra comercial.
3. Cliente não herda permissões internas do representante.
4. LLM não acessa banco, credenciais Meta ou escolhe livremente destinatário humano.
5. Plano A e Plano B reutilizam o mesmo motor comercial do CRM.
6. F6 (campanhas) e F7 (conversa contínua) são escopos separados.

## Histórico da PoC

As afirmações anteriores de que Coexistence não estava comprovado, que `smb_message_echoes` não havia sido observado e que Plano A dependia da PoC básica foram superadas pela validação registrada na página canônica. O roteiro e seus critérios foram preservados como histórico na [Fonte — Plano A / Plano B WhatsApp](../90_references/CRM_TEXTIL_FONTE_PLANO_A_B_WHATSAPP.md), para explicar a origem das decisões sem representar o estado atual.

## Próximos limites arquiteturais

Antes de implementar F7 ou declarar Plano A comercialmente completo, fechar contrato de eventos Gateway → CRM, correlação e autoria, persistência e retenção, políticas customer-facing, corridas humano × bot, handoff, reassunção e observabilidade. Ver [F7 — Conversação híbrida](../40_delivery/F7_WHATSAPP_HYBRID_CONVERSATION.md).
