# Comportamento de conversa — proposta para integração com o Gateway

O CRM permite salvar rascunhos separados por empresa e tipo de robô:
`ASSISTANT` (representante) e `COEXISTENCE` (atendimento ao cliente). Eles
não são publicados nem consumidos pelo Gateway ainda. A edição não altera
respostas existentes. Os padrões mostrados na tela só são gravados ao salvar.

## Comportamento desejado

- Manter contexto por empresa, linha, tipo de robô e interlocutor, sem misturar
  clientes, representantes ou conversas em linhas diferentes.
- Usar uma janela deslizante de 120 minutos por padrão. Após 120 minutos ou mais
  sem mensagem, iniciar novo contexto; uma saudação de retorno é opcional e
  adequada ao conteúdo, não uma resposta obrigatória. O início da conversa não
  significa apagar o histórico comercial ou substituir regras de retenção.
- Cumprimentar quando apropriado, sem repetir o nome ou a saudação em cada
  resposta. Responder ao que a pessoa realmente disse.
- Se a intenção estiver incerta, pedir esclarecimento ou dizer que não consegue
  ajudar com o pedido. Nunca oferecer tabela ou executar outra ação sem relação
  com a mensagem e o contexto; confirmações existentes continuam vinculadas à
  ação que as originou e não devem ser reaproveitadas após expirar.
- O tom e as orientações influenciam redação, não permitem alterar preços,
  permissões, carteira, consentimento, handoff ou autorizar envio.

## Contrato a negociar

O Gateway é dono do canal e da conversa operacional. Antes de implementar,
definir um contrato autenticado e versionado para obter configurações por tenant
e linha comprovada, aplicar limites de tamanho e número de mensagens no contexto,
definir relógio, tratamento de eventos duplicados e fora de ordem, concorrência,
expiração de ações pendentes, cache, indisponibilidade e política de retenção.
As configurações são rascunhos: decidir publicação e confirmação de aplicação
antes de apresentá-las como ativas. Sem contrato, não supor que o Gateway lê
automaticamente estas tabelas ou que o CRM possui todas as mensagens necessárias.

Testar nos dois papéis: sequência de mensagens, pedidos ambíguos, troca de
assunto, 119 e 120 minutos de silêncio, nova mensagem que reinicia a janela,
isolamento entre linhas/usuários/tenants, pedido confirmado e ação expirada,
falhas do CRM e intervenção humana. A Coexistence segue os gates de F7 e a
resposta humana deve prevalecer sobre automação.
