# Modelo de domínio

| Agregado | Responsabilidade |
|---|---|
| Tenant | Isolamento lógico |
| Customer / Contact | Empresa, UF, pessoa e WhatsApp |
| ProductFamily / Product | Catálogo técnico normalizado |
| PreferredProduct | Seleção, ordem e alias por cliente |
| PriceList / Item | Competência, vigência, preço e disponibilidade |
| CommercialTerm | Desconto ou acréscimo |
| FreightRule / TaxRule | Frete e tributação explícitos |
| Offer / OfferItem | Fluxo de aprovação e fotografia imutável |
| Conversation / Message | Contexto e histórico de interação |
| InboundEvent | Idempotência externa |
| OutboundMessage | Entrega pelo Gateway |

## Estados

- Oferta: `DRAFT → PENDING_APPROVAL → APPROVED → SENT`, com `REJECTED`, `FAILED` e `CANCELLED`.
- Disponibilidade: `AVAILABLE`, `OUT_OF_STOCK`, `SUSPENDED`, `FUTURE_ARRIVAL`, `CONSULT`.

## Invariantes

- SKU único por tenant.
- Telefone ativo identifica no máximo um contato por tenant.
- Uma preferência ativa por cliente e produto.
- Oferta enviada depende de aprovação e snapshot próprio.
