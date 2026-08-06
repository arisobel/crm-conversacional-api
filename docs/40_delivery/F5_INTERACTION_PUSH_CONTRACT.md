# Contrato de push de interações — Gateway → CRM

Complemento de R5 do [plano F5](F5_REPRESENTATIVE_PORTAL.md). Ver ADR-016.

**Estado: o lado do CRM está implementado; o lado do Gateway não.** Este
documento existe para que a implementação no outro repositório não precise
adivinhar nada — e para deixar registrado que ela ainda não foi feita.

## Por que o CRM não puxa

O CRM não é dono da conversa. `conversations` e `messages` continuam no
Gateway. O que o CRM guarda é uma **projeção**: o suficiente para a ficha do
cliente montar a linha do tempo sem consultar o Gateway a cada abertura de tela,
e não um arquivo da conversa.

A direção do fluxo é uma decisão, não um detalhe. Puxar exigiria que o CRM
soubesse quando algo mudou — ou seja, uma varredura periódica que ou atrasa a
ficha ou martela o Gateway. Empurrar coloca o custo onde a informação nasce.

## Endpoint

```
POST /internal/interactions
```

Autenticação: o mesmo HMAC das demais rotas internas. Os cabeçalhos
`X-Tenant-Slug`, `X-Timestamp` e `X-Signature` são obrigatórios, e a assinatura
canoniza `timestamp.MÉTODO.caminho.corpo` — **o corpo entra na assinatura**, o
que significa assinar exatamente os bytes que serão enviados, não o objeto antes
de serializar.

Corpo:

```json
{
  "interactions": [
    {
      "external_ref": "wamid.HBgNNTUxMTk5...",
      "direction": "INBOUND",
      "occurred_at": "2026-08-06T13:42:11Z",
      "whatsapp_e164": "+5511988887777",
      "summary": "Bom dia, tem 75/36 cru disponível?",
      "channel": "WHATSAPP",
      "source": "whatsapp-gateway",
      "payload": {"message_type": "text"}
    }
  ]
}
```

Até 200 eventos por chamada. `whatsapp_e164` **ou** `customer_id` é obrigatório.

Resposta, sempre `200` quando a autenticação passa:

```json
{
  "created": 1,
  "duplicated": 0,
  "rejected": 0,
  "results": [
    {"external_ref": "wamid.HBg...", "outcome": "CREATED", "interaction_id": "..."}
  ]
}
```

## As quatro regras que o Gateway precisa respeitar

**1. Reenviar é seguro, e é o mecanismo de retry.** A chave
`(tenant, source, external_ref)` é única no banco. Reenviar o mesmo evento
devolve `DUPLICATE` e não duplica a linha do tempo. Use o id da mensagem no
WhatsApp como `external_ref` — ele já é estável e único.

**2. Um item recusado não invalida o lote.** Cada evento é gravado em um
savepoint próprio e a resposta traz o desfecho de cada um. Se o lote inteiro
falhasse por causa de um evento órfão, o Gateway reenviaria para sempre os que
já tinham sido aceitos. Trate `REJECTED` item a item: `reason` diz o que houve,
e a correção quase sempre é cadastrar o contato no CRM, não repetir a chamada.

**3. O push não pode bloquear a resposta ao contato.** Esta é a exigência que
mais importa e a única que o CRM não consegue garantir sozinho. O envio ao CRM
acontece **depois** de a mensagem ao contato ter sido tratada, fora do caminho
crítico. Se o CRM estiver fora do ar, a pessoa do outro lado do WhatsApp não
pode perceber. Enfileire e tente de novo; não espere.

**4. Evento sem cliente resolvido é recusado, não gravado.** Um telefone que não
corresponde a nenhum contato do tenant devolve `REJECTED`. Um registro sem dono
não apareceria em ficha alguma e ainda assim guardaria conteúdo de conversa.

## Retenção

O CRM não apaga nada por conta própria. `CRM_INTERACTION_RETENTION_DAYS` define
a política, e sem ela o expurgo **recusa rodar**:

```bash
python -m crm_api.admin_cli purge-interactions --days 365 --dry-run
python -m crm_api.admin_cli purge-interactions --days 365
```

O `--dry-run` executa a remoção dentro da transação e desfaz, então o número
relatado é o real. Toda execução efetiva grava em `audit_log` com o corte, a
política aplicada e a contagem.

Por quanto tempo conteúdo de conversa pode ficar guardado é **Q3**, e continua
sem resposta. Enquanto não houver decisão, a ausência de política é o
comportamento seguro: nada é apagado, e nada é apagado por engano.

## O que falta

- [ ] Implementar o push no Gateway, assíncrono e com retry.
- [ ] Decidir Q3 e configurar `CRM_INTERACTION_RETENTION_DAYS`.
- [ ] Agendar o expurgo (cron do CapRover ou execução manual periódica).
