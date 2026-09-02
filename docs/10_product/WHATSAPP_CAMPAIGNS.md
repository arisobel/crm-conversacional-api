# Campanhas de WhatsApp

**Estado:** especificação e backlog; não implementado. Este documento não
autoriza envio, não altera o Gateway e não cria contrato executável.

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

## Responsabilidades

| Assunto | CRM-API | Gateway / Meta Cloud API |
|---|---|---|
| Carteira, clientes, contatos e representantes | Fonte de verdade e autorização | Consome somente os dados necessários ao envio |
| Público e filtros comerciais | Resolve de forma determinística, congela a prévia e audita | Recebe o público confirmado |
| Template de marketing | Escolhe apenas entre os permitidos | Mantém o cadastro operacional, a aprovação Meta e o envio do template |
| Consentimento e opt-out | Exibe o resultado devolvido; não presume consentimento | Fonte de verdade, aplica na prévia e imediatamente antes de cada envio |
| Envio, limites Meta e estados do canal | Mantém projeção comercial | Executa, controla a Meta e emite eventos operacionais |
| Histórico da ficha | Persiste a projeção e aplica escopo de carteira | Produz mensagens, estados e respostas no canal |

O Gateway continua dono de `messages`, conversas, consentimento, opt-out e
status operacionais. A projeção do CRM não substitui esses registros nem tenta
reconciliá-los por consulta direta ao banco do Gateway.

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
- A cópia local do Gateway usada nesta análise não contém
  `whatsapp-marketing-broadcast-v1.md` nem `meta_whatsapp_campaigns.js`; suas
  decisões específicas devem ser conferidas no repositório/fonte correspondente
  antes de qualquer implementação integrada.

## Ordem de implementação proposta

O plano de entrega vigente é o [F6](../40_delivery/F6_WHATSAPP_CAMPAIGNS.md),
registrado em 2026-09-02 a partir do roteiro aprovado. Ele mantém as etapas
abaixo, com um ajuste de ordem: o portal (F6.3) pode ser entregue **antes** da
integração com o Gateway, com a confirmação bloqueada ou simulada — nunca
apresentando "enviado" para o que é apenas rascunho.

1. Fechar as pendências de negócio, política de retenção e contrato entre os
   dois serviços.
2. Criar no CRM o modelo, resolvedor de audiência, prévia determinística,
   autorização por carteira, snapshots e auditoria, sem envio.
3. Implementar no Gateway catálogo operacional de templates, consentimento,
   comando idempotente, fila/rate limit e emissão de eventos.
4. Integrar os contratos com fixture e testes de replay, falha parcial,
   consentimento revogado e isolamento de carteira.
5. Entregar portal de campanhas e projeção na ficha do cliente; só então
   habilitar as capabilities conversacionais que tiverem executor validado.
