# Linha Assistente — política e vínculo das linhas de representantes

**Estado:** o portal administra a política com auditoria e o CRM a filtra no
manifesto. Os executores ainda não recebem contexto de linha: este contrato só
fica ativo quando CRM e Gateway entregarem a versão v2 juntos.

## Regra de produto

A Linha Assistente é o núcleo operacional do tenant, não um número, nome ou
representante específico. Toda linha WhatsApp conectada e autorizada de um
usuário `REPRESENTATIVE` é vinculada a ela. A operação ocorre em nome do dono
da linha de origem: carteira e capacidades continuam individuais.

Patrick Rangel Consultor é uma instância dessa regra, nunca exceção ou fallback.
A Linha Assistente também não é a linha comercial que fala com clientes; esse
atendimento continua sob Coexistence/F7.

## Política por organização e representante

O CRM é autoridade da configuração por organização e representante. Guardar
ativação da organização, ativação individual e conjunto explícito de IDs de
capacidades; ausência de configuração nega. A política efetiva é a interseção
da ativação nos dois níveis e das capacidades selecionadas para o indivíduo,
limitadas às capacidades de representante com executor conhecido. Configuração
não substitui usuário ativo, tenant, autenticação, carteira ou permissões de
cada operação. Só administrador do tenant poderá alterar, com auditoria.

A função pura `AssistantPolicy` e o repositório de leitura já implementam essa
parte da decisão. O vínculo de linha será consumido pelos executores. No
contrato v2, a Linha Assistente falha fechada para cliente, representante
inativo, conexão ausente/desconectada ou política ausente/vazia.

## Contrato Gateway → CRM v2

`POST /api/integrations/whatsapp/v1/capabilities/manifest` já recebe telefone e
`channel_context.line_phone_number_id` no corpo HMAC. Para a BPTI,
`CRM_ASSISTANT_LINE_PHONE_NUMBER_ID` recebe o Phone Number ID Meta
`1164849720052678`, nunca o número exibido de qualquer representante.

O v2 deve transportar, em manifesto e em cada executor, um contexto coberto
pela assinatura:

| Campo | Validação do CRM |
|---|---|
| `assistant_line_phone_number_id` | Casa com a Linha Assistente do tenant. |
| `representative_line_reference` | Identifica uma única conexão `CONNECTED`. |
| `representative_phone_e164` | Resolve o dono daquela conexão, que deve estar ativo. |
| `request_id` | Correlaciona auditoria e idempotência. |

O CRM consulta a conexão por `(tenant, representative_line_reference)` e exige
que seu `representative_user_id` seja o ator resolvido pelo telefone. Contexto
ausente, ambíguo, desconectado ou divergente nega; nunca escolhe outra linha ou
representante. O Gateway deve serializar o contexto no corpo ou incluí-lo na
cadeia canônica HMAC — cabeçalho solto não basta.

O manifesto é descoberta com cache, não autorização final. Cada executor
revalida contexto, conexão, ator, política, capacidade e carteira. Sem fonte de
política ou contexto validado, falha fechado, sem fallback para cliente,
manifesto legado ou outro representante.

## Comportamentos e erros a acordar com o Gateway

| Situação | Comportamento requerido |
|---|---|
| Organização ou representante desativado, configuração ausente | Negar atendimento do assistente; não conceder capacidades de cliente. |
| Linha de origem ausente, desconectada, ambígua ou de outro representante | Negar; nunca trocar de representante. |
| Ator desconhecido, inativo, ambíguo ou cliente na linha assistente | Negar; nunca trocar para manifesto legado. |
| Capacidade não permitida ou revogada | Negar na execução, mesmo com manifesto em cache. |
| Linha ausente, desconhecida, não vinculada ao tenant ou divergente | Negar na linha assistente; não escolher outra linha por suposição. |
| CRM indisponível ou erro de autenticação | Não executar nem usar capacidades antigas como autorização; resposta operacional conforme contrato futuro. |
| Linha comercial | Manter contratos, escopo e atendimento existentes. |

O CRM devolve `403` para a Linha Assistente sem representante elegível ou sem
política efetiva. O Gateway deve tratar isso como negação, sem cair em
manifesto legado, cliente ou cache antigo; validar o caminho real antes do
deploy.

## Próximas entregas

1. Publicar o contexto assinado v2 nos dois repositórios e fazê-lo chegar a
   manifesto e executor.
2. Revalidar no CRM, em cada executor, conexão, política, capacidade e carteira;
   cache é somente otimização de descoberta.
3. Testar dois representantes conectados à mesma Linha Assistente: capacidades e
   carteiras isoladas, linha cruzada, desconexão, desativação e cache revogado.
4. Depois do teste integrado, ativar uma única linha real para o piloto das
   quatro funções já publicadas: buscar artigo, localizar cliente, consultar a
   tabela do cliente e abrir pré-cadastro.

## Handoff e rotina da Linha Assistente

O handoff parte da linha Coexistence: ela informa ao cliente que vai verificar,
encerra a automação daquela conversa e pede ao Gateway que notifique pela Linha
Assistente o representante da **linha de origem** e os administradores ativos.
O resumo deve conter cliente, conversa, motivo normalizado do handoff e ponto
de continuidade. Não há fallback para outro representante.

A rotina inicia às 07h30 e resume às 18h30, no horário de Brasília. Ela pode
lembrar pendências verificáveis, mas não inventa resumo ou próxima ação. Handoff
e rotina são comandos operacionais CRM ↔ Gateway, não capabilities deste
manifesto: só entram quando o Gateway registrar executores, idempotência,
destinatários e eventos. Mensagens iniciadas fora da janela de atendimento do
destinatário exigem template Meta aprovado; preparar os templates é pré-requisito
da ativação.
