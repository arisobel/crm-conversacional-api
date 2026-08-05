# Direção do produto — CRM de representantes

Definida em: 2026-08-04. Substitui a leitura anterior de que o WhatsApp era a
interface primária do sistema.

## O que muda

O produto deixa de ser "uma API conversacional que responde tabela no WhatsApp"
e passa a ser **um CRM operado por representantes comerciais**, no qual o
WhatsApp é um canal entre outros.

| Antes | Agora |
|---|---|
| Interface primária: WhatsApp via Gateway | Interface primária: portal do representante |
| Cliente é resolvido por telefone | Cliente pertence a um representante titular |
| Tabela de preços é lida por contato | Tabela é gerida por competência e resolvida por localidade |
| ICMS previsto mas nunca exercido | ICMS é regra de primeira classe, por par de UF |
| Conversa é persistência técnica | Interação é histórico comercial exibido ao representante |

O Gateway, o HMAC, o cálculo determinístico e a proibição de a LLM produzir
preço permanecem válidos. Nenhum ADR anterior é revogado por esta direção,
exceto onde os novos ADRs dizem o contrário.

## Personas

| Persona | O que faz |
|---|---|
| Representante | Atende sua carteira, consulta preço para a UF do cliente, acompanha o histórico de interações |
| Administrador comercial | Cadastra representantes, publica a tabela do mês, mantém a matriz de ICMS |
| Cliente comprador | Recebe a tabela pelos produtos que lhe interessam, já com o ICMS da sua localidade |

## Capacidades-alvo

1. **Gerir representantes** — cadastro, login, papel e carteira de clientes.
2. **Gerir clientes por representante** — o representante enxerga apenas a sua
   carteira; o administrador enxerga todas.
3. **Tabela de preços por competência** — a chave de idempotência comercial é
   `(tenant, YYYYMM, produto)`. Reimportar o mesmo mês corrige o preço vigente,
   não cria uma segunda tabela.
4. **Preço resolvido por localidade** — o preço entregue ao cliente é derivado
   do preço-base pela alíquota de ICMS do par `UF de origem → UF do cliente`.
5. **Lista personalizada** — a lista enviada a um cliente contém os produtos
   preferidos dele, na ordem e com o alias dele, já convertidos para a UF dele.
6. **Histórico de interações** — timeline por cliente, alimentada pelo Gateway,
   visível na ficha do cliente.

## Escopo do primeiro corte

Dentro:

- Representante como usuário autenticado com carteira.
- Localidades de entrega/trabalho do cliente com UF.
- Preço vigente por competência com revisão e ativação auditáveis.
- Matriz de ICMS por par de UF, com especialização por produto, família e cliente.
- Projeção de interações WhatsApp alimentada pelo Gateway.
- Telas: carteira, ficha do cliente, tabela do mês, matriz de ICMS.

Fora:

- Substituição tributária, DIFAL, redução de base e Simples Nacional.
- Representante multiempresa (ver "Backlog congelado" abaixo).
- Oferta autônoma, negociação por LLM e envio sem aprovação.
- Importação automática de PDF.

## Backlog congelado

O [backlog de representante multiempresa](MULTI_COMPANY_BACKLOG.md) descrevia
"representante" como **organização que representa várias empresas fornecedoras**.
A direção aprovada adota o outro significado: representante é **usuário com
carteira dentro de um tenant**. O documento permanece como referência histórica
e está congelado; seus itens `MC-001` a `MC-007` saem do backlog priorizado.

Se um dia a organização representante multiempresa voltar, ela é um eixo
**adicional** — não substitui o representante-usuário definido aqui.

## Impacto no roadmap anterior

| Fase antiga | Destino |
|---|---|
| F0 Fundação | Concluída, mantida |
| F1 Cadastros e tabela vigente | Mantida; a consulta por WhatsApp continua em contrato |
| F2 Preços e condições | Reescrita como R3 + R4 (competência e ICMS) |
| F3 Oferta | Despriorizada; volta depois do portal |
| F4 Gateway | Reduzida à ingestão de interações (R5) |

O detalhamento das novas fases está em
[F5 — Portal do representante](../40_delivery/F5_REPRESENTATIVE_PORTAL.md) e o
modelo de dados em [modelo-alvo](../20_domain/DOMAIN_MODEL_TARGET.md).

## Questões abertas que bloqueiam implementação

| # | Questão | Bloqueia |
|---|---|---|
| Q1 | O preço-base carregado já contém ICMS embutido? Qual alíquota? | R4 |
| Q2 | A conversão entre UFs usa cálculo "por dentro" (padrão) ou acréscimo simples? | R4 |
| Q3 | Retenção e visibilidade do histórico de interações sob LGPD | R5 |
| Q4 | A UI vive neste repositório ou em aplicação separada? | R6 |

Q1 e Q2 são decisões fiscais, não técnicas, e precisam de confirmação
contábil antes de R4 ser implementada. A proposta técnica está no modelo-alvo.
