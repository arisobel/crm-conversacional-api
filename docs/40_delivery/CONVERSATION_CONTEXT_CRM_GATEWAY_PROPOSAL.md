# Proposta: contexto e configuração entre CRM e Gateway

Estado: proposta para acordo entre equipes; não implementada nem publicada.
O Gateway permanece autoridade operacional da conversa e do canal.

## Diagnóstico no CRM

`POST /internal/interactions` aceita lotes HMAC, deduplica por tenant, origem e
referência externa, e devolve resultados por item. O envio informado é de melhor
esforço: pode atrasar, falhar ou ser recusado. A projeção usa `summary`, que
pode ser resumo, ser vazio ou estar truncado; não garante texto integral. Não
guarda identidade confiável de aplicativo, linha, fluxo, conversa ou papel do
robô. Eventos sem contato ou usuário resolvido são recusados; a timeline por
cliente pode incluir contatos diferentes e notas manuais. As rotas de leitura
existentes usam sessão de usuário, não são API interna de conversa. Elas não
devem ser utilizadas como contexto do robô.

`conversation_behavior_settings` guarda por tenant e `bot_kind` o tom,
orientações, janela e data de alteração. Os valores são rascunhos, não há API
para o Gateway, versão publicada ou confirmação de aplicação. Os padrões na
tela só são persistidos quando o administrador salva. Não há configuração por
linha; incluir tal precedência exigiria um contrato e modelo novos.

O verificador HMAC atual autentica timestamp, método, caminho e corpo; valida
o tenant configurado, mas o cabeçalho de tenant e a query string não compõem
a assinatura. Não reaproveitar essa forma para dados de isolamento colocados
em cabeçalhos ou parâmetros sem reforçar o contrato.

## Identidade e autorização

Propor identidade composta canônica: tenant, aplicação do Gateway, referência
técnica estável de linha, fluxo, `bot_kind` e identificador opaco do
interlocutor/conversa emitido pelo Gateway. O Gateway deve provar que aplicação,
linha e fluxo pertencem ao tenant e ao papel; o CRM deve validar essa associação
em registro confiável, com política para vínculos ativos e revogados. O vínculo
de Coexistence existente (`gateway_line_reference`) é uma projeção comercial,
não prova automaticamente todos os demais componentes; a linha assistente ainda
precisa de vínculo próprio. Número de exibição e `customer_id` isolado não são
identificadores de conversa. Conflitos, ausência ou identidade não verificável
devem negar a leitura, sem tentar outra linha, papel, contato ou tenant.

Propor autenticação de serviço separada e autorizada por tenant/aplicação e
operação, com identidade e todos os parâmetros sensíveis no corpo assinado de
uma requisição versionada. Assinar método, caminho, corpo, timestamp e tenant,
com proteção a replay adequada; credenciais e escopos específicos devem ser
definidos entre equipes. O HMAC atual não vincula sozinho uma linha a um tenant
ou autoriza a leitura daquele interlocutor. Evitar dados pessoais e corpo de
mensagens em URLs e logs; auditoria operacional deve registrar acesso, escopo,
resultado e correlação, sem conteúdo.

## Leitura de contexto proposta

Uma operação interna de leitura versionada, com método e caminho a acordar,
receberia no corpo a identidade completa validada, um limite superior temporal
exclusivo e limites desejados. O CRM deve impor teto próprio: até 10 mensagens e
500 caracteres por mensagem inicialmente, e uma janela máxima limitada pela
política efetiva. O Gateway fornece o instante da mensagem atual e garante que
ela não apareça duas vezes; a ordenação e o tratamento de eventos tardios devem
usar um identificador estável de evento como desempate. O CRM seleciona as
mais recentes dentro da janela, devolve em ordem cronológica e inclui ids
estáveis, instante UTC, autoria/direção e texto utilizável. Uma data isolada
não resolve empates: usar cursor composto ou chave estável para seleção e
deduplicação. Rejeitar timestamps inválidos ou excessivamente futuros.

Retornar junto: identidade resolvida, limites realmente aplicados, origem e
estado de cobertura `UNKNOWN`, `PARTIAL` ou `COMPLETE`, com razão e eventual
marco de cobertura verificável. A projeção atual só pode ser `UNKNOWN` ou
`PARTIAL`; número de mensagens e timestamp não provam completude. `COMPLETE`
exige ingestão durável, confirmação, reconciliação e watermark que demonstre
ausência de lacunas para a conversa e intervalo. Um resultado vazio significa
somente que não há registros elegíveis disponíveis, não que não houve conversa.

Não gravar nem retornar contexto de forma segura até existir armazenamento de
eventos com todos os componentes de identidade validados, autoria e conteúdo
adequado. Uma migração/contrato de ingestão versionado, índices, deduplicação,
rejeição de conflitos e política de retenção explícita são necessários. Dados
legados sem identidade completa não devem ser inferidos nem misturados.
Combinar histórico remoto e memória local somente por id de evento estável,
com a mesma identidade, cronologia e limites. A memória local recente do
Gateway prevalece quando houver conflito; divergência deve ser observável.

## Configuração proposta

Criar operação interna distinta para obter a configuração **publicada** por
tenant e `bot_kind`, mediante vínculo de linha validado. Resposta proposta:
versão imutável, tom, orientações, minutos de contexto e data de publicação.
O CRM deve ter rascunho e publicação explícita auditada, versionamento e
validação de tamanho/tom; a tabela atual, sozinha, não representa publicação.
Uma configuração ausente ou rascunho não deve substituir a atual no Gateway.
Mudanças de `ASSISTANT` não alteram nem invalidam o comportamento ou cache de
`COEXISTENCE`; se não houver configuração publicada para Coexistence, manter o
funcionamento vigente desse papel. Definir cache, prazo, invalidação por versão,
rollback e indicação de versão efetivamente aplicada antes de ligar a leitura.

As orientações são dados de redação de administrador, nunca autorização nem
instrução para ignorar regras do sistema, preços, carteira, consentimento,
confirmação ou handoff. Resposta de configuração não comprova autorização de
ações: o CRM continua revalidando as operações em seus executores.

## Indisponibilidade e implementação gradual

Leitura de contexto deve ter prazo curto e não bloquear indefinidamente o
atendimento: em erro, identidade inválida ou cobertura desconhecida, usar apenas
a memória local já isolada e o comportamento vigente do papel; após reinício,
tratar o contexto como ausente ou parcial e pedir esclarecimento se necessário.
Não executar ação, assumir continuidade ou reproduzir confirmação anterior com
base em histórico incompleto. Registrar métricas sem texto e diferenciar erro,
lista vazia e cobertura parcial. Não confundir falha da leitura de contexto com
falha da autorização obrigatória para ações: esta permanece fechada.

Ordem sugerida: (1) acordar identidade, autenticação, retenção e semântica de
cobertura; (2) implementar ingestão durável e armazenamento isolado com
reconciliação; (3) habilitar leitura de contexto com testes e flag por papel;
(4) implementar publicação de configurações e leitura versionada; (5) ativar
primeiro `ASSISTANT` e validar; `COEXISTENCE` continua independente e só muda
com ativação específica e testes próprios. Testar tenants, linhas, contatos,
papéis, timestamps iguais, mensagens fora de ordem/duplicadas, reinícios,
lacunas, indisponibilidade, revogação e intervenção humana.
