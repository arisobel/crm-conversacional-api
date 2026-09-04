# Campanhas de WhatsApp

**Estado:** direção de produto e especificação funcional; implementação parcial
em F6. O CRM já possui modelo de campanha, resolvedor determinístico de
audiência e portal para prévia/rascunho. O envio integrado CRM → Gateway e a
estratégia de sender ainda dependem das etapas posteriores e da validação
técnica aplicável.

## Objetivo e limite

Campanhas de WhatsApp (ou mensagens em lote) permitem que o CRM prepare,
revise e acompanhe comunicações comerciais destinadas a clientes da carteira.
O resultado deve aparecer em duas perspectivas: um resumo agregado da campanha
e a mensagem, o status e a resposta na ficha de cada cliente alcançado.

O CRM é um CRM de representantes. Portanto, a campanha começa sempre por uma
seleção comercial determinada a partir dos dados do tenant; ela não é um atalho
para enviar uma mensagem a uma lista de telefones. Este corte não cria template
na Meta, não infere público, não escolhe destinatário com LLM e não envia texto
livre de marketing fora da janela de 24 horas.

## Motor comercial único e estratégias de canal

O CRM-api possui **um único motor comercial de campanhas**. Ele identifica o
representante, restringe a carteira, aplica os critérios, resolve a audiência de
forma determinística, coleta a confirmação e congela os snapshots da campanha.
O Gateway executa a campanha confirmada usando a estratégia de canal adequada.

```text
Comando / Portal
       |
       v
CRM-api
       |
       +-- identidade do representante
       +-- carteira
       +-- critérios
       +-- audiência
       +-- template pretendido
       +-- confirmação
       +-- snapshot
       |
       v
Campanha comercial confirmada
       |
       v
Gateway
       |
       +---------------------------+
       |                           |
       v                           v
 Plano A                        Plano B
 linha do representante        linha WABA central
```

> A estratégia de sender não cria um segundo motor de campanhas. O CRM-api
> continua responsável pela decisão comercial; o Gateway continua responsável
> pelo canal.

## Responsabilidades

| Assunto | CRM-API | Gateway / Meta Cloud API |
|---|---|---|
| Carteira, clientes, contatos e representantes | Fonte de verdade e autorização | Consome somente os dados necessários ao envio |
| Público e filtros comerciais | Resolve de forma determinística, congela a prévia e audita | Recebe o público confirmado |
| Estratégia de sender e identidade técnica de envio | Identifica o representante dono da campanha, sem conhecer credenciais Meta | Resolve a linha WhatsApp autorizada do representante ou a linha WABA central de fallback |
| Template de marketing | Escolhe apenas entre os permitidos | Mantém o cadastro operacional, a aprovação Meta e o envio do template |
| Consentimento e opt-out | Exibe o resultado devolvido; não presume consentimento | Fonte de verdade, aplica na prévia e imediatamente antes de cada envio |
| Envio, limites Meta e estados do canal | Mantém projeção comercial | Executa, controla a Meta e emite eventos operacionais |
| Histórico da ficha | Persiste a projeção e aplica escopo de carteira | Produz mensagens, estados e respostas no canal |

O Gateway continua dono de `messages`, conversas, consentimento, opt-out e
status operacionais. A projeção do CRM não substitui esses registros nem tenta
reconciliá-los por consulta direta ao banco do Gateway.

### Autoridades preservadas

- **CRM-api:** representante, carteira, cliente, contatos, grupos,
  segmentação, audiência, permissões, campanha comercial, snapshots, auditoria
  e projeção comercial.
- **Gateway:** linha WhatsApp, `phone_number_id`, WABA, credenciais Meta,
  templates operacionais, consentimento/opt-out, estratégia de sender, envio,
  webhooks, statuses, mensagens e correlação do canal.
- **Meta:** WhatsApp Business Platform, WABA, templates aprovados, qualidade,
  limites, janela de atendimento e entrega.

## Estratégias de canal

### Plano A — identidade do representante

O Plano A é a direção preferencial. O representante inicia a campanha pelo
portal ou por comando conversacional; o CRM-api identifica o ator, restringe a
ação à sua carteira, resolve a audiência de forma determinística e congela a
campanha. O Gateway então resolve a identidade técnica de envio autorizada para
esse representante e envia pelo número WhatsApp Business dele.

```text
Representante
     |
     | comando
     v
Gateway
     |
     v
CRM-api
     |
     | audiência / autorização
     v
Campanha
     |
     v
Gateway
     |
     | sender = identidade WhatsApp
     |          vinculada ao representante
     v
Cliente

Depois:

Representante <---- conversa direta ----> Cliente
```

Assim, o cliente vê o número do próprio representante e, após o disparo, ambos
podem continuar a conversa diretamente. Conceitualmente, representante/usuário
e identidade técnica WhatsApp de envio são distintos, embora vinculados: o CRM
identifica o dono da campanha; o Gateway resolve a linha autorizada no canal.
`phone_number_id`, credenciais e demais ativos Meta permanecem sob autoridade do
Gateway.

O Plano A depende da validação prática de **WhatsApp Coexistence**. É uma
direção preferencial e tecnicamente promissora, condicionada a PoC técnico no
Gateway; não significa que o CRM já implemente Coexistence, nem que o Gateway já
processe todos os seus eventos específicos. O contexto de origem está em
[Fonte — Plano A / Plano B WhatsApp](../90_references/CRM_TEXTIL_FONTE_PLANO_A_B_WHATSAPP.md).

A continuidade conversacional posterior à campanha, inclusive a evolução futura
de conversação híbrida Humano + IA na identidade do representante, é uma frente
própria. Ela não expande o escopo de F6.

### Plano B — WABA central com proxy

Se o Plano A encontrar impedimento real no PoC ou na operação, o Plano B é o
fallback: o Gateway envia pela linha WABA central e correlaciona tecnicamente as
respostas dos clientes, que podem ser retransmitidas ao representante. Uma
resposta humana do representante deve usar correlação determinística por Reply e
contexto técnico; a LLM nunca escolhe o destinatário dessa resposta humana.

O detalhe da máquina de relay pertence a uma arquitetura futura, caso esse
fallback se torne necessário. O Plano B permanece documentado como contingência
e não substitui a direção preferencial do Plano A.

## Visibilidade no portal

| Perfil | Pode ver e fazer |
|---|---|
| `REPRESENTATIVE` | Criar prévia e acompanhar somente campanhas próprias e clientes cuja `owner_user_id` seja o seu. Nunca pode incluir cliente de outra carteira. |
| `MANAGER` e `ADMIN` | Acompanhar todas as campanhas do tenant e filtrar por representante. A permissão de criar, confirmar e cancelar acima da própria carteira será definida junto à alçada comercial. |

A futura tela lista por período, situação, representante, template e segmentos.
O detalhe mostra público, critérios, template, variáveis, contagens e os
destinatários. Cada destinatário informa `PENDING`, `SENT`, `DELIVERED`,
`READ` ou `FAILED`, resposta quando houver e exclusão por falta de consentimento.
A navegação campanha → ficha do cliente e a seção de campanhas na ficha são
requisitos de aceite, não recursos opcionais da interface.

## Público e segmentação

O resolvedor de audiência recebe apenas critérios estruturados e produz uma
prévia reproduzível. Ele aplica tenant, papel e carteira antes de qualquer outro
filtro. Resultado sem critério existente é erro orientado ao usuário: o fluxo
conversacional pede uma alternativa; nunca monta um público "plausível" por
suposição.

| Eixo | Situação | Uso na campanha |
|---|---|---|
| `product_groups` | Implementado: N↔N entre artigo e grupo, do tenant | Eixo de produto preferencial. Reutiliza grupos como poliéster e alta-tenacidade; não usa `product_families`, que é layout da tabela. Falta implementar o filtro de clientes por grupo. |
| Produtos preferenciais | Implementado em `customer_preferred_products` | Permite selecionar clientes ligados aos artigos/grupos escolhidos; antes do envio é preciso confirmar o significado comercial de “preferido” como sinal de compra. |
| Fibra/composição | Implementado em `fibers` e `product_compositions` | Pode compor segmentos como “clientes de poliéster” por meio dos produtos. Produto sem composição é **não classificado**, não evidência de ausência da fibra. |
| Porte | Não modelado | Será atributo declarado em eixo exclusivo, por exemplo `porte=grande|pequeno`; nunca será inferido de compra, oferta ou volume inexistente. |
| Lista de julgamento | Não modelada | Lista não exclusiva, com proprietário e regra de visibilidade explícitos. A decisão de privacidade/compartilhamento entre representantes permanece aberta. |

Critérios derivados podem ser reavaliados para construir a prévia, mas a
campanha confirmada conserva a fotografia dos critérios e dos destinatários. A
fotografia evita que uma mudança posterior de grupo, carteira ou preferência
altere o que foi efetivamente aprovado e enviado.

## Templates, consentimento e confirmação

Templates de marketing são aprovados e mantidos na Meta; o CRM só apresenta os
templates permitidos pelo Gateway. Fora da janela de 24 horas, marketing usa
template Meta com variáveis permitidas — não há texto livre como alternativa.

Consentimento de marketing é obrigatório. O Gateway precisa avaliá-lo duas
vezes: na prévia, para explicar quantos contatos serão excluídos, e novamente
imediatamente antes de cada tentativa de envio. Uma revogação entre a revisão e
o envio prevalece sobre a confirmação; o CRM recebe e exibe a exclusão, sem
tentar reenviar.

Toda escrita segue a sequência abaixo e é auditável:

1. Resolver critérios e retornar apenas prévia, contagens e exclusões.
2. Criar rascunho com critérios, template e variáveis congelados.
3. Revisar nominalmente os destinatários quando o público superar o limite
   configurável — **350 destinatários** (ADR-029); para público menor, a
   confirmação pode ocorrer pelo WhatsApp quando houver executor validado.
4. Confirmar explicitamente, com chave de idempotência e nova validação de
   autorização no CRM.
5. O Gateway revalida consentimento antes de cada envio, executa o lote e envia
   eventos de resultado ao CRM.

Cancelar só pode afetar um rascunho, uma campanha ainda não iniciada ou a parte
pendente. O que já foi aceito pela Meta continua como fato histórico.

## Histórico, auditoria e retenção

O CRM preservará o pedido original, ator, critérios, lista congelada, template,
variáveis, confirmação, identificadores externos e resultados recebidos. A
mensagem enviada e a resposta continuam eventos do Gateway, mas suas referências
de campanha alimentam tanto o detalhe agregado como a timeline do cliente.

Repetição de comando, entrega HTTP ou evento não pode criar nova campanha,
duplicar destinatário nem duplicar o resultado de uma mensagem. As chaves e os
estados exatos ainda serão fechados no contrato, mas a implementação deve ter
idempotência de comando e de evento desde o primeiro corte.

As campanhas adicionam dados comerciais e pessoais à projeção do CRM. A política
de retenção, inclusive relação com `CRM_INTERACTION_RETENTION_DAYS`, permanece
pendente de decisão LGPD; nenhuma rotina pode expurgar este histórico por um
prazo implícito.

## Evolução conversacional

Os comandos conversacionais desta seção correspondem ao incremento F6.5 sobre o
motor de campanhas. Eles não abrangem a continuidade conversacional posterior ao
disparo, que é uma evolução própria e não deve ampliar F6.

A LLM pode reconhecer o pedido e extrair somente slots declarados. A resolução
de público, a autorização, a escolha efetiva de clientes e qualquer escrita são
determinísticas. As capacidades abaixo são proposta de evolução do manifesto
`business-capability-manifest/v1`; não devem ser anunciadas enquanto o Gateway
não tiver allowlist e executor compatíveis.

| Intenção de negócio histórica | Capability proposta | Modo | Executor futuro |
|---|---|---|---|
| `BROADCAST_OFERTA` | `CRM_PREVIEW_WHATSAPP_CAMPAIGN_AUDIENCE` | leitura | CRM resolve critérios e devolve prévia; Gateway apenas apresenta |
| `COMUNICAR_DISPONIBILIDADE_E_PRECO` | `CRM_CREATE_WHATSAPP_CAMPAIGN_DRAFT` | escrita confirmada e idempotente | CRM congela rascunho; Gateway recebe-o somente após contrato fechado |
| `COMUNICAR_DISPONIBILIDADE_E_PRECO` | `CRM_CONFIRM_WHATSAPP_CAMPAIGN` | escrita confirmada e idempotente | CRM revalida alçada; Gateway executa a campanha confirmada |
| — | `CRM_CANCEL_WHATSAPP_CAMPAIGN` | escrita confirmada e idempotente | CRM solicita cancelamento; Gateway interrompe apenas pendências |
| — | `CRM_GET_WHATSAPP_CAMPAIGN_STATUS` | leitura | CRM apresenta sua projeção dos eventos do Gateway |
| `GERAR_LISTA_PROSPECCAO` | `CRM_PREVIEW_WHATSAPP_CAMPAIGN_AUDIENCE` quando o objetivo for campanha | leitura | Não cria campanha nem escreve lista |
| `REGISTRAR_INTERESSE` | permanece capacidade de CRM de cliente | escrita confirmada e idempotente | Não é campanha; pode enriquecer futuro critério somente se modelado |
| `CONSULTAR_HISTORICO_CLIENTE` | permanece leitura da ficha/timeline | leitura | Exibe também referências de campanhas vinculadas |

Os nomes são estáveis como candidatos, não ações aprovadas. Antes de entrar no
manifesto, cada um exige: slots e vocabulário definidos, ação allowlisted no
Gateway, executor local, teste de contrato, confirmação e idempotência exigidas
para escrita. Isso respeita ADR-022 a ADR-026 e evita publicar uma ação que o
Gateway ainda não sabe executar.

## Riscos e decisões pendentes

- ~~Limite que exige revisão nominal no portal~~ — decidido em 2026-09-02:
  **350 destinatários** (ADR-029). A alçada de confirmação/cancelamento acima
  da própria carteira permanece aberta.
- Regra de visibilidade e compartilhamento das listas de julgamento.
- Significado comercial de produto “preferido” para segmentação.
- Catálogo de templates permitidos, variáveis, idioma e política de frequência.
- Contrato final de comando CRM → Gateway, eventos Gateway → CRM, replay e
  reconciliação após indisponibilidade.
- Retenção LGPD de rascunhos, destinatários, conteúdo projetado e respostas.

## Ordem de implementação proposta

O plano de entrega vigente é o [F6](../40_delivery/F6_WHATSAPP_CAMPAIGNS.md).
F6.1, F6.2 e F6.3 já materializam o motor comercial no CRM sem envio integrado.
A direção de produto para as próximas etapas é:

```text
Motor comercial CRM
        |
        v
F6.1 / F6.2 / F6.3
        |
        v
PoC Coexistence no Gateway
        |
        +---- GO ----> Plano A / sender do representante
        |
        +---- NO-GO -> Plano B / fallback central
        |
        v
F6.4 integração CRM ↔ Gateway
        |
        v
F6.5 comandos conversacionais
```

O PoC decide a estratégia de sender antes do desenho definitivo da integração.
A F6.4 continua responsável pelo contrato e pela integração CRM ↔ Gateway; F6.5
continua sendo o incremento de comandos sobre o motor já validado. Esta ordem
não altera o arquivo F6 nesta sessão.
