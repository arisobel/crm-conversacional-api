# Arquitetura

```mermaid
flowchart TD
    M["Meta Cloud API"] --> G["WhatsApp Gateway"]
    G --> C["CRM Conversacional API"]
    C --> D[("PostgreSQL")]
    C --> L["LLM"]
    C --> G
```

## Responsabilidades

**Gateway:** valida webhooks, normaliza e roteia eventos, envia mensagens e acompanha status técnico.

**CRM API:** identifica cliente, consulta catálogo/preços, calcula condições, cria/aprova ofertas, persiste conversas e expõe operações controladas.

**LLM:** classifica intenção e redige respostas com dados fornecidos pela API.

## Segurança entre serviços

HTTPS, assinatura HMAC, timestamp com tolerância, chave rotacionável, idempotência e segredos somente em variáveis de ambiente.
