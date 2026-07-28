# Modelo de domínio

| Agregado | Responsabilidade |
|---|---|
| Tenant | Isolamento lógico da operação |
| Customer | Empresa compradora e UF padrão |
| CustomerContact | Pessoa e número WhatsApp |
| ProductFamily | Agrupamento e ordem de apresentação |
| Product | Item técnico normalizado |
| PreferredProduct | Seleção e nome específico por cliente |
| PriceList | Competência e vigência comercial |
| PriceListItem | Preço e disponibilidade do produto |
| CommercialTerm | Desconto ou acréscimo aplicável |
| FreightRule | Frete por UF e unidade |
| TaxRule | Regra tributária explícita |
| Offer | Estado, aprovação e texto final |
| OfferItem | Fotografia imutável do cálculo |
| Conversation | Contexto de interação por contato |
| Message | Registro de entrada e saída |
| InboundEvent | Idempotência do evento externo |
| OutboundMessage | Entrega pelo Gateway |

## Estados principais

Oferta: `DRAFT → PENDING_APPROVAL → APPROVED → SENT`, com saídas `REJECTED`, `FAILED` ou `CANCELLED`.

Disponibilidade: `AVAILABLE`, `OUT_OF_STOCK`, `SUSPENDED`, `FUTURE_ARRIVAL`, `CONSULT`.

## Invariantes

- um SKU é único dentro do tenant;
- um telefone WhatsApp ativo identifica no máximo um contato dentro do tenant;
- apenas uma relação preferencial ativa existe por cliente e produto;
- itens de oferta não dependem de consultas posteriores para reconstruir seu valor;
- uma oferta só pode ser enviada após aprovação;
- a competência usa o primeiro dia do mês.
