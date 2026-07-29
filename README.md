# CRM Conversacional API

API de domínio e persistência do CRM integrado ao WhatsApp Gateway. Ela armazena e
consulta clientes, contatos, catálogo, tabelas de preço, regras comerciais e ofertas;
o Gateway continua responsável pela Meta Cloud API, roteamento e envio de mensagens.

## Objetivo

Gerar ofertas comerciais personalizadas, corretas e auditáveis com catálogo, produtos preferenciais, tabela vigente, regras determinísticas e aprovação humana.

## Limites

- **WhatsApp Gateway:** Meta Cloud API, roteamento e entrega.
- **CRM API:** clientes, catálogo, preços, ofertas, conversas e persistência.
- **LLM:** interpretação e redação; nunca fonte de preço ou SQL livre.

## Documentação

- [Índice](docs/README.md)
- [Orquestração](docs/00_meta/AGENT_SKILL_ORCHESTRATION.md)
- [Progresso](docs/00_meta/07_progress.md)
- [Roadmap](docs/10_product/MVP_ROADMAP.md)
- [Regras de negócio](docs/20_domain/BUSINESS_RULES.md)
- [Arquitetura](docs/30_architecture/ARCHITECTURE.md)
- [DDL PostgreSQL](db/migrations/0001_initial.sql)
- [OpenAPI](openapi/crm-api.yaml)

## Estado

F0 — fundação executável em desenvolvimento. O primeiro corte expõe saúde, readiness
do banco e resolução de cliente por WhatsApp.

## Desenvolvimento local

Pré-requisitos: [uv](https://docs.astral.sh/uv/), Docker Compose e Python 3.12+ (o uv
pode instalá-lo automaticamente).

```powershell
Copy-Item .env.example .env
uv sync --group dev
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn crm_api.main:app --reload
```

Em outro terminal, confirme a saúde:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/ready
```

Para executar tudo em contêineres, depois de ajustar o segredo de desenvolvimento:

```powershell
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose up -d api
```

O volume `postgres_data` preserva o banco local. `.env` não é versionado.

## Comandos de qualidade

```powershell
uv run ruff check .
uv run pytest
```

## Chamada interna do Gateway

`GET /customers/by-whatsapp/{phone}` é uma operação entre serviços. O Gateway precisa
resolver previamente o tenant pelo fluxo da linha Meta e enviar `X-Tenant-Slug`,
`X-Timestamp` (ISO 8601 UTC) e `X-Signature`. A assinatura é o hexadecimal de
HMAC-SHA256 de `timestamp.method.path.body`, usando `CRM_INTERNAL_HMAC_SECRET`; no GET,
o corpo é vazio. Consulte o [contrato da API](docs/30_architecture/API_CONTRACT.md).

Exemplo de formato de resposta:

```json
{
  "customer_id": "uuid",
  "customer_name": "Tecelagem Exemplo Ltda.",
  "state_code": "SP",
  "contact_id": "uuid",
  "contact_name": "Vitória Exemplo",
  "whatsapp_e164": "+5511999999999"
}
```

Os valores da tabela comercial de referência não são dados de demonstração nem seed.
Importação de PDF, cadastro e cálculo de preços continuam nas fases posteriores.
