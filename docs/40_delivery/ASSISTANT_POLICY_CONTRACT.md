# Linha assistente — política e integração proposta

**Estado:** regra e modelo de persistência preparados localmente, ainda sem
administração, painel, aplicação ao manifesto ou execução. Não muda o contrato do Gateway e
não ativa nem desativa atendimento. Não fazer deploy como controle de acesso.

## Escopo e modelo proposto

O CRM é autoridade da configuração por organização e representante. Guardar
ativação da organização, ativação individual e conjunto explícito de IDs de
capacidades; ausência de configuração nega. A política efetiva é a interseção
da ativação nos dois níveis e das capacidades selecionadas para o indivíduo,
limitadas às capacidades de representante com executor conhecido. Configuração
não substitui usuário ativo, tenant, autenticação, carteira ou permissões de
cada operação. Só administrador do tenant poderá alterar, com auditoria.

A função pura `AssistantPolicy` e o repositório de leitura implementam esta
decisão a partir dos dados persistidos, mas ainda não são mecanismos de
autorização em produção.

## Contrato existente e lacuna

`POST /api/integrations/whatsapp/v1/capabilities/manifest` recebe telefone e
`channel_context.line_phone_number_id`, HMAC e tenant. Retorna ator, capacidades,
ajuda e TTL. O envelope atual não prova por si só que a linha é assistente: é
necessário estabelecer vínculo confiável entre referência da linha e tenant,
além de um acordo para indicar e validar esse papel. Não usar número de exibição
como identidade técnica. Desconhecido, ausente ou conflitante não pode liberar
capacidade de representante na linha assistente nem cair no manifesto legado.
Linha comercial deve continuar com seu fluxo e manifesto existentes.

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

Os códigos HTTP e envelopes de erro específicos dependem de validação com o
Gateway. Não se deve supor que qualquer 403, 404 ou lista vazia já provoque o
comportamento desejado; validar o caminho real e evitar fallback permissivo.

## Próximas entregas

1. Administração autenticada e auditada dos dados; painel em etapa posterior.
2. Acordar e versionar identidade de linha e contexto de execução autenticados;
   atualizar contrato, OpenAPI e decisões antes da integração.
3. Aplicar política no manifesto **e em cada executor**, manter autorização de
   carteira e definir efeito de mudanças em cache e requisições em andamento.
4. Testar no CRM e no Gateway: desativação organizacional e individual, cada
   capacidade, isolamento entre tenants/representantes, linha comercial intacta,
   cache anterior à revogação, erros, indisponibilidade, ator cliente e ausência de
   fallback. Validar contrato e migração em PostgreSQL antes de implantação.

Horários, avisos, campanhas e rotina diária não são implementados por este corte.
