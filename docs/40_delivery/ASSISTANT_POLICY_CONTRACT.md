# Linha assistente — política e integração proposta

**Estado:** o portal administra a política com auditoria e o CRM a aplica ao
manifesto da Linha Assistente quando o Gateway informa o `phone_number_id`
configurado. Ainda falta a revalidação em cada executor do Gateway e o teste
integrado; não tratar este corte isolado como ativação completa em produção.

## Escopo e modelo proposto

O CRM é autoridade da configuração por organização e representante. Guardar
ativação da organização, ativação individual e conjunto explícito de IDs de
capacidades; ausência de configuração nega. A política efetiva é a interseção
da ativação nos dois níveis e das capacidades selecionadas para o indivíduo,
limitadas às capacidades de representante com executor conhecido. Configuração
não substitui usuário ativo, tenant, autenticação, carteira ou permissões de
cada operação. Só administrador do tenant poderá alterar, com auditoria.

A função pura `AssistantPolicy` e o repositório de leitura implementam esta
decisão a partir dos dados persistidos. A linha configurada falha fechada para
cliente, representante inativo ou política ausente/vazia; a linha comercial
permanece fora deste filtro.

## Contrato existente e lacuna

`POST /api/integrations/whatsapp/v1/capabilities/manifest` recebe telefone e
`channel_context.line_phone_number_id`, HMAC e tenant. Retorna ator, capacidades,
ajuda e TTL. Para a BPTI, `CRM_ASSISTANT_LINE_PHONE_NUMBER_ID` recebe o
identificador Meta `1164849720052678`; ele nunca é substituído pelo número de
exibição `+5511939401738`. Quando os dois IDs casam, o CRM exige representante
ativo e filtra o manifesto pela política persistida. Linha comercial deve
continuar com seu fluxo e manifesto existentes.

O manifesto não é uma autorização final: pode permanecer em cache e as rotas
atuais de execução do representante recebem telefone, mas não identificam a
linha. Filtrar somente o manifesto permitiria execução com política revogada ou
em contexto errado. Antes de aplicar a política deve haver contexto confiável de
linha em cada execução e revalidação no CRM de tenant, ator, estado da política,
ação e carteira; expiração e invalidação do cache também devem ser acordadas.
Sem contexto validado ou fonte de política disponível, falhar fechado para a
linha assistente, sem fallback para capacidades de cliente ou manifesto legado.

## Comportamentos e erros a acordar com o Gateway

| Situação | Comportamento requerido |
|---|---|
| Organização ou representante desativado, configuração ausente | Negar atendimento do assistente; não conceder capacidades de cliente. |
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

1. Revalidar a política no Gateway em cada executor, manter autorização de
   carteira e definir efeito de mudanças em cache e requisições em andamento.
2. Testar no CRM e no Gateway: desativação organizacional e individual, cada
   capacidade, isolamento entre tenants/representantes, linha comercial intacta,
   cache anterior à revogação, erros, indisponibilidade, ator cliente e ausência de
   fallback. Validar contrato e migração em PostgreSQL antes de implantação.

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
