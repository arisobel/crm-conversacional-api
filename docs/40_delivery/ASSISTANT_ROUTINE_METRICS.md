# Métricas e parâmetros operacionais — Linha Assistente

**Estado:** especificação para a próxima entrega. Não ativa agendamento, envio
ou coleta de telemetria por si só.

## Objetivo

Medir a rotina da Linha Assistente sem transformar uma projeção incompleta em
fato comercial. Em especial, `clientes_atendidos` e `compras_fechadas` só podem
ser exibidos quando houver uma fonte integrada, correlacionada à linha e com
cobertura conhecida. Dado indisponível é `UNKNOWN`, nunca zero.

## Parâmetros de operação

| Parâmetro | Valor inicial | Regra |
|---|---:|---|
| Fuso da rotina | `America/Sao_Paulo` | Um único fuso explícito para agendamento e supressão diária. |
| Início da rotina | `07:30` | Pode ser antecipado uma vez pelo representante. |
| Resumo diário | `18:30` | Pode ser solicitado antes; a antecipação suprime o envio automático daquele dia local. |
| Janela de atraso | 15 min | Após isso, registrar atraso; não disparar duas vezes para compensar. |
| Tentativas de entrega | 3 | Backoff controlado no Gateway e idempotência por rotina, representante e dia local. |
| Prazo da chave de idempotência | 48 h | Cobre reprocessamento e atrasos sem reenvio duplicado. |
| Contexto de conversa | até 10 eventos / 500 caracteres por evento | Teto já proposto para leitura de contexto; o CRM aplica limite próprio. |
| Retenção de telemetria agregada | 13 meses | Sem texto de mensagens, telefone, nome, `wamid` ou identificador de cliente nas métricas. |

Alterar horário, fuso, tentativas ou retenção exige configuração versionada,
auditoria e publicação explícita. A configuração só produz efeito depois de
confirmada pelo Gateway.

## Eventos mínimos

Cada execução deve gerar eventos técnicos correlacionáveis, sem conteúdo de
mensagem:

| Evento | Campos obrigatórios |
|---|---|
| `assistant_routine_due` | `routine`, `local_date`, `scheduled_at`, `tenant_id`, `representative_id` |
| `assistant_routine_started` | campos acima + `execution_id`, `trigger` (`SCHEDULED` ou `MANUAL`) |
| `assistant_routine_completed` | campos acima + `outcome`, `duration_ms`, `data_coverage` |
| `assistant_routine_delivery` | `execution_id`, `attempt`, `status`, `provider_code`, `duration_ms` |
| `assistant_routine_suppressed` | `routine`, `local_date`, `reason` (`ALREADY_COMPLETED`, `POLICY_DISABLED`, `OUTSIDE_WINDOW`) |
| `assistant_metric_source_status` | `metric`, `availability` (`AVAILABLE`, `PARTIAL`, `UNKNOWN`), `reason` |

`tenant_id` e `representative_id` ficam no evento de auditoria protegido; não
entram como labels de série temporal, para evitar cardinalidade e exposição.

## Métricas publicadas

| Métrica | Tipo | Labels de baixa cardinalidade | Leitura |
|---|---|---|---|
| `assistant_routine_executions_total` | contador | `routine`, `trigger`, `outcome` | Tentativas concluídas, falhas e execuções idempotentes. |
| `assistant_routine_due_to_start_seconds` | histograma | `routine` | Atraso real da rotina frente ao horário marcado. |
| `assistant_routine_duration_seconds` | histograma | `routine`, `outcome` | Tempo de composição, sem incluir conteúdo. |
| `assistant_delivery_attempts_total` | contador | `routine`, `status`, `attempt_bucket` | Entrega aceita, falha transitória, falha terminal ou desconhecida. |
| `assistant_delivery_latency_seconds` | histograma | `routine`, `status` | Latência até a resposta do Gateway/provedor. |
| `assistant_routine_suppressions_total` | contador | `routine`, `reason` | Supressões corretas e causa. |
| `assistant_data_coverage_total` | contador | `metric`, `availability`, `reason` | Distingue fonte parcial/desconhecida de valor zero. |
| `assistant_authorization_denials_total` | contador | `operation`, `reason` | Falhas fechadas de política, linha, conexão ou escopo. |
| `assistant_context_reads_total` | contador | `result`, `coverage` | Sucesso, vazio, parcial, rejeitado ou erro da leitura de contexto. |

`outcome` é limitado a `SENT`, `NOT_SENT`, `FAILED`, `SKIPPED`; `status` a
`ACCEPTED`, `TRANSIENT_FAILURE`, `TERMINAL_FAILURE`, `UNKNOWN`. Nenhuma label
pode carregar telefone, UUID, nome, texto, template completo ou código de erro
bruto.

## Indicadores de produto e sua fonte

| Indicador solicitado no resumo | Estado atual | Regra de apresentação |
|---|---|---|
| Clientes atendidos pela linha | `UNKNOWN` | Só mostrar após contrato de eventos do Gateway definir linha, interlocutor, período e deduplicação. |
| Compras fechadas | `UNKNOWN` | Só mostrar após integração de pedido/compra, critério de fechamento e correlação confiável. |
| Pendências verificáveis | `PARTIAL` | Pode mostrar apenas itens com fonte e dono explícitos; informar cobertura parcial. |
| Entrega da rotina | `AVAILABLE` após executor | Indicador técnico, separado de resultado comercial. |

## Metas iniciais para o piloto

- 99% das rotinas vencidas iniciadas em até 15 minutos, por semana;
- menos de 0,5% de duplicidade de execução ou entrega;
- 100% dos resumos comerciais com `data_coverage` explícita;
- 100% das recusas de autorização registradas sem conteúdo da conversa;
- alerta se falha terminal de entrega superar 2% em 30 minutos, ou se a fonte
  de um indicador comercial passar a `UNKNOWN` depois de ter ficado disponível.

As metas são critérios de observação do piloto, não SLA contratual. Antes de
ativar envio, o Gateway e o CRM devem concordar sobre evento, correlação,
idempotência, retenção e quem recebe cada alerta.
