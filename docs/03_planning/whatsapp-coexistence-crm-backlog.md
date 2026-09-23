# Backlog — onboarding WhatsApp Coexistence no CRM

**Natureza:** planejamento de produto e integração interna.  
**Estado:** vertical slice P0 implementado no CRM em 2026-09-23; depende de Gateway configurado e do fluxo Meta em produção.
**Escopo:** experiência comercial para conectar o WhatsApp Business de um representante ao Gateway. O CRM não integra diretamente com a Meta.

## Objetivo e fronteira de responsabilidade

O CRM deve permitir que uma pessoa autorizada inicie e acompanhe o onboarding de WhatsApp Business de um representante com pouca interação técnica:

```text
Ficha do representante
  → Conectar WhatsApp
  → CRM cria onboarding no Gateway
  → CRM abre launch_url em popup/modal
  → usuário conclui Embedded Signup
  → CRM acompanha o estado sanitizado
  → ficha mostra número conectado
```

| Responsabilidade | Autoridade |
|---|---|
| Tenant, representante, carteira, permissões, regras comerciais e experiência | CRM |
| Embedded Signup, OAuth Meta, token, WABA, `phone_number_id`, apps inscritas, linha técnica, routing e webhook | Gateway |

O CRM **nunca** armazena token Meta, App Secret, ciphertext, OAuth code ou credenciais Graph API. `phone_number_id` não é a única identidade de negócio: o vínculo comercial deve identificar a conexão externa e a linha de Gateway associadas ao representante.

Este backlog complementa a arquitetura conceitual de [WhatsApp Coexistence e conversa híbrida](../30_architecture/WHATSAPP_REPRESENTATIVE_COEXISTENCE.md). Ele não substitui o PoC do Gateway nem inicia F6.4 ou F7.

## Priorização

| Prioridade | Épicos | Resultado |
|---|---|---|
| P0 | C1, C2, C3, C4, C5, C6, C7, C8 | Vertical slice de conectar e acompanhar uma linha |
| P1 | C9 | Linha vinculada disponível para usos comerciais posteriores |
| P2 | C10 | Operação avançada, troubleshooting e recuperação |

## Épicos

### C1 — Modelo de vínculo representante ↔ integração (P0)

Definir o modelo de domínio e a relação entre `representative`, `external_channel_connection`, onboarding do Gateway e referência de linha do Gateway. O vínculo precisa ter identidade própria, ciclo de vida e auditoria; uma referência técnica isolada não representa a conexão comercial.

**Aceite de planejamento:** fica explícito como uma conexão pertence ao tenant e ao representante, como sua referência externa é preservada e como se evita vincular uma linha a representante ou tenant incorreto.

### C2 — Estado de conexão (P0)

Definir uma projeção de UX, separada do diagnóstico técnico detalhado do Gateway:

```text
NOT_CONNECTED → CONNECTING → CONNECTED
                    ├── ACTION_REQUIRED
                    ├── DEGRADED
                    └── DISCONNECTED
```

`CONNECTED` não dispensa a existência de um estado técnico do Gateway. O CRM exibe mensagens comerciais e sanitizadas; não infere ou replica a máquina de estado da Meta.

**Aceite de planejamento:** cada estado informa ação permitida ao usuário e origem da transição (início, polling, cancelamento ou atualização do Gateway).

### C3 — API interna CRM → Gateway (P0)

Planejar um cliente interno para as operações abaixo, com a autenticação HMAC ou mecanismo interno já padronizado, idempotência e correlação:

```text
POST onboarding
GET  onboarding status
POST cancel
POST retry/resume
```

Os nomes de rotas, payloads, tempos de expiração e semântica de idempotência serão fechados no contrato do Gateway; este épico não cria endpoints no CRM.

**Aceite de planejamento:** cada chamada possui identidade de tenant, representante, conexão e chave de correlação, sem segredo Meta no request, response, log ou auditoria do CRM.

### C4 — Seção WhatsApp na ficha do representante (P0)

Planejar uma seção na ficha com estado, número exibível, ação de conectar, reconectar quando permitida, cancelar onboarding e espaço para futura remoção ou desconexão. A seção deve manter o representante como dono comercial da experiência, sem expor detalhes de OAuth ou Graph API.

**Aceite de planejamento:** o usuário consegue entender se há conexão, se uma ação está em curso e qual é a próxima ação válida.

### C5 — Modal e jornada de onboarding (P0)

Ao acionar conectar, o CRM cria o onboarding no Gateway, recebe `launch_url`, abre popup ou modal, acompanha a conclusão, atualiza a ficha e fecha a janela quando apropriado. Falha, cancelamento e expiração retornam a um estado de UX compreensível e uma ação segura.

**Aceite de planejamento:** o fluxo não exige que o usuário manipule token, WABA, `phone_number_id` ou URL técnica fora da jornada fornecida.

### C6 — Polling e atualização de status (P0)

No MVP, usar polling controlado do status no Gateway, limitado à conexão e à janela de onboarding em andamento. Em evolução, substituir ou complementar por callback interno Gateway → CRM idempotente e autenticado.

**Aceite de planejamento:** a interface deixa de consultar ao concluir, cancelar ou expirar; repetição de resposta não cria vínculo ou auditoria duplicados.

### C7 — RBAC (P0)

Revisar o RBAC atual antes de decidir as permissões de conectar, reconectar, cancelar e consultar diagnóstico técnico. Os candidatos são `ADMIN_PLATAFORMA`, `ADMIN_CLIENTE` e `REPRESENTANTE`, mas esses papéis não são uma decisão deste documento.

**Aceite de planejamento:** a matriz final separa ação sobre a própria linha, ação sobre linha de outro representante e visibilidade de detalhes técnicos.

### C8 — Auditoria de negócio (P0)

Registrar, sem segredos, os eventos abaixo com tenant, representante, conexão, ator, data e correlação:

```text
WHATSAPP_CONNECTION_STARTED
WHATSAPP_CONNECTION_COMPLETED
WHATSAPP_CONNECTION_FAILED
WHATSAPP_CONNECTION_CANCELLED
```

**Aceite de planejamento:** o histórico comercial explica a jornada sem persistir URL de lançamento, token, código OAuth ou diagnóstico sensível.

### C9 — Uso comercial da linha (P1)

Após o onboarding estar estável, planejar a associação da linha do Gateway ao representante para timeline, campanhas, inbound, outbound e modos human/bot. Esse trabalho depende das decisões e dos gates já definidos para F6 e F7; não é parte do primeiro corte.

### C10 — UX operacional (P2)

Planejar reconexão, token revogado, linha degradada, desconexão, mensagens de troubleshooting e eventual remoção. A UX deve explicar impacto e próximo passo sem revelar credenciais ou detalhes de Meta desnecessários.

## Contrato mínimo e dependências obrigatórias do Gateway

O CRM depende de um contrato estável do Gateway que forneça:

| Capacidade | Garantia esperada |
|---|---|
| Criar onboarding | Referência correlacionável e `launch_url` de curta duração, sem credenciais expostas ao CRM |
| Consultar status | Estado sanitizado, número exibível quando disponível e indicação de ação necessária/falha |
| Cancelar | Operação idempotente que encerra ou marca a jornada técnica adequadamente |
| Retomar/tentar novamente | Semântica explícita para sessão expirada, falha recuperável e conexão já concluída |
| Segurança operacional | Autenticação interna, escopo de tenant, autorização de representante, correlação, idempotência e logs sem segredos |

O Gateway continua dono de `launch_url`, Embedded Signup, OAuth, WABA, `phone_number_id`, tokens, inscrições de app, linha técnica, webhook e routing. O CRM não chama Graph API, não duplica a lógica Meta e não usa banco do Gateway.

## Vertical slice inicial (P0)

O primeiro corte entrega somente:

```text
Representante elegível
  → Conectar WhatsApp
  → popup/modal com Embedded Signup provido pelo Gateway
  → estado CONNECTING no CRM
  → Gateway informa COMPLETED/status sanitizado
  → CRM mostra número conectado e CONNECTED
```

Ficam explicitamente fora desse corte: campanhas, timeline completa, human/bot, reconexão avançada, múltiplas linhas por representante, dashboard técnico, remoção definitiva e callbacks internos em tempo real.

## Decisões ainda abertas

- Resultado do PoC de Coexistence e GO/NO-GO do Plano A.
- Modelo físico e cardinalidade: uma linha por representante no MVP, e regras para substituição, histórico e futuras múltiplas linhas.
- Contrato concreto, versionamento, TTL de `launch_url`, idempotência, erros recuperáveis e reconciliação entre CRM e Gateway.
- Matriz de RBAC após revisão dos papéis efetivos do CRM.
- Regra de apresentação/mascaramento do número e nível de diagnóstico visível por perfil.
- Cadência, timeout e custo do polling; desenho e entrega posterior de callback Gateway → CRM.
- Semântica de desconectar/remover e consequências para campanhas e conversas em curso.
- Retenção LGPD de eventos de auditoria e dados de conexão sanitizados.

## Limites desta entrega documental

O vertical slice P0 possui UI, endpoints CRM, migration e cliente interno do Gateway. Não houve chamada Graph API, OAuth Meta no CRM, persistência de credenciais, alteração no Gateway, commit ou push.
