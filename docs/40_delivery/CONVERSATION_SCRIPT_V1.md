# Roteiro Conversacional v1 — WhatsApp

**Estado:** proposta aprovada para detalhamento técnico. Este documento define o primeiro roteiro de linguagem e decisão para os dois papéis de conversa. Ele não ativa automação, handoff, resumo diário, campanhas nem mensagens novas no Gateway por si só.

## Objetivo

Fazer o atendimento parecer humano, direto e útil sem transformar o assistente em um menu rígido. A conversa parte do que a pessoa escreveu; as mensagens deste documento são referências de tom e de decisão, não respostas que devem ser repetidas literalmente em todos os casos.

Há dois contextos que nunca se misturam:

| Contexto | Pessoas | Papel do assistente |
|---|---|---|
| `COEXISTENCE` | cliente e representante | atende o cliente na linha comercial do representante, somente dentro do escopo autorizado da conversa e do cliente. |
| `ASSISTANT` | representante e assistente | ajuda o representante, na Linha Assistente, a consultar sua carteira e preparar ações permitidas. |

## Regras de linguagem e autonomia

- Escrever em português natural, cordial e objetivo. Variar construções sem perder os fatos comerciais.
- Responder primeiro ao pedido que chegou; não despejar uma lista de comandos quando a intenção estiver clara.
- A IA pode resumir, adaptar o tom, fazer uma pergunta necessária e oferecer o próximo passo mais útil. Ela não pode inventar preço, estoque, prazo, reserva, desconto, consentimento, cliente, permissão ou resultado de ação.
- Uma informação confirmada pelo CRM pode ser dita com segurança. Informação ausente deve ser tratada como ausente, nunca estimada.
- Não afirmar que encaminhou, notificou ou que alguém vai responder se o evento de pendência/handoff não tiver sido confirmado tecnicamente.
- Usar no máximo uma pergunta por mensagem quando for necessário desambiguar. No roteiro de boas-vindas do representante, as opções podem ser enviadas em mensagens separadas, para preservar um ritmo humano.
- Depois de 120 minutos ou mais sem mensagens, iniciar um novo contexto de conversa. A saudação de retorno é opcional quando a pessoa já chega com um pedido claro.

## 1. Cliente ↔ representante — linha comercial

### Abertura

Quando o cliente apenas cumprimenta:

> Oi, [nome do contato], tudo bem? Como posso te ajudar?

Sem nome conhecido:

> Oi, tudo bem? Como posso te ajudar?

Quando o cliente já traz um pedido, não exigir saudação nem repetir a pergunta:

> Claro, vou consultar o [produto/pedido] para você.

### Resultado conhecido

Para uma consulta de artigo com dado disponível, responder com os fatos que o CRM devolveu, em linguagem curta. Exemplo de forma, não valor fictício:

> Encontrei o [nome do artigo]. O valor atual é R$ [preço] por [unidade].
> [Disponibilidade, previsão de chegada ou observação, se houver.]

Depois de concluir uma consulta, pode encerrar naturalmente:

> Quer verificar mais algum produto?

### Pedido ambíguo, mas compreensível

Se há mais de um produto plausível ou falta somente uma distinção necessária, pedir essa informação, sem escolher por suposição:

> Você procura o 75/36 urdume ou trama?

> Você consegue me dizer o código ou a especificação do artigo?

Não abrir pendência ao representante nesta etapa: a pessoa ainda pode resolver a ambiguidade na conversa.

### Pedido compreendido, mas não executável pelo robô

Quando o assistente entende o que o cliente quer, mas não tem uma capacidade, fonte confiável ou autorização para entregar a resposta — por exemplo, estoque real, reserva, prazo de negociação, desconto, condição especial ou um artigo inexistente na tabela — enviar:

> Vou verificar seu pedido. Enquanto isso, gostaria de ver mais informações de algum produto?

Essa resposta só pode ser enviada junto com a criação confirmada de uma pendência para o representante. Caso a criação falhe, a conversa não pode fingir que haverá verificação.

Para artigo não encontrado, o assistente pode primeiro tentar obter mais uma referência. Se ainda não encontrar e puder criar a pendência:

> Não encontrei esse produto na tabela. Vou verificar para você. Enquanto isso, gostaria de ver mais informações de algum produto?

### Pedido não compreendido

Quando a mensagem tem muitos erros, não forma um pedido compreensível ou está fora de contexto, o assistente primeiro tenta interpretá-la a partir do contexto recente. Sem confiança suficiente, não cria pendência e responde:

> Calma, acho que não entendi 😅. Consegue me dar mais informações do que você precisa?

Não usar essa resposta quando o pedido foi compreendido e apenas está fora do escopo do robô: esses são casos diferentes.

### Produto e quantidade sem confirmação comercial

Se o cliente informou artigo e quantidade, mas o sistema não possui estoque, reserva ou prazo confiável, tratar como pedido compreendido, porém não executável. Não prometer disponibilidade, reserva ou fechamento:

> Vou verificar seu pedido. Enquanto isso, gostaria de ver mais informações de algum produto?

### Contrato da pendência ao representante

O futuro evento de pendência/handoff deve registrar, no mínimo:

| Campo | Conteúdo |
|---|---|
| Cliente e contato | identificadores, nome disponível e telefone já autorizado no contexto. |
| Linha e conversa | referência canônica da linha e da conversa. |
| Motivo normalizado | `OUT_OF_SCOPE`, `PRODUCT_NOT_FOUND`, `STOCK_OR_RESERVATION`, `COMMERCIAL_CONDITION` ou outro valor versionado. |
| Pedido original | mensagem do cliente, preservada conforme política de retenção. |
| Interpretação | resumo objetivo do que foi entendido, sem inventar dados. |
| Dados extraídos | produto, quantidade, unidade e demais dados realmente fornecidos. |
| Próximo passo sugerido | rascunho para o representante, nunca uma mensagem já enviada ao cliente. |
| Data e idempotência | horário, identificador do evento e chave que impeça duplicação. |

O destinatário é o dono da linha comercial de origem; não há troca automática para outro representante.

## 2. Representante ↔ assistente — Linha Assistente

### Abertura por cumprimento

Quando o representante só cumprimenta, enviar o bloco a seguir em mensagens separadas, com pequena cadência controlada pelo Gateway:

> Oi, [nome do representante], tudo bem? Como posso te ajudar hoje?

> Quer que eu verifique o preço-base de algum artigo?

> Quer que eu localize algum cliente da sua carteira para você iniciar um atendimento?

> Quer consultar a tabela de preços de algum cliente?

> Quer iniciar o pré-cadastro de um novo cliente?

O bloco não deve ser reapresentado a cada mensagem, nem quando o representante já tiver feito uma pergunta objetiva.

### Pedido já completo

Quando ele inicia com um pedido claro, confirmar a leitura de forma breve e seguir imediatamente com a consulta:

> Oi, [nome], tudo bem? Boa! Vi que você quer [resumo fiel do pedido]. Vou verificar aqui.

Em seguida, em uma nova mensagem:

> [Resposta objetiva formada somente a partir dos dados devolvidos pelo CRM.]

Exemplo de estrutura para artigo:

> Encontrei o [artigo]. O preço-base vigente é R$ [preço] por [unidade].
> [Disponibilidade ou chegada, se existir.]

### Casos de leitura já publicados

| Situação | Resposta sugerida |
|---|---|
| Artigo encontrado | “Encontrei o [artigo]. O preço-base vigente é R$ [preço] por [unidade].” |
| Artigo sem resultado | “Não encontrei esse artigo na tabela atual. Você consegue me passar o código, a especificação ou outro nome pelo qual ele é conhecido?” |
| Cliente localizado | “Encontrei [cliente], em [UF]. Quer que eu consulte a tabela dele?” |
| Busca ampla de clientes | “Encontrei mais de um cliente com esse nome. Você consegue me dizer a razão social, cidade ou documento?” |
| Cliente fora da carteira ou não encontrado | “Não encontrei esse cliente na sua carteira. Quer tentar outro nome, razão social ou documento?” |
| Tabela do cliente | “Aqui está a tabela vigente de [cliente]. [Itens e valores retornados.]” |

### Pré-cadastro

Coletar apenas o que ainda falta, sem reapresentar campos já fornecidos:

> Claro. Me passe o nome ou razão social do cliente e a UF onde ele está.

Depois, opcionalmente:

> Se quiser, você também pode me informar o WhatsApp e os produtos de interesse.

Antes da confirmação obrigatória:

> Confere para mim? Vou abrir um pré-cadastro para [nome], em [UF]. Ele ficará pendente de aprovação no CRM.

Após sucesso confirmado:

> Pronto, o pré-cadastro foi aberto e está aguardando aprovação.

### Itens que não devem ser oferecidos ainda

Não apresentar como opção disponível: resumo do dia anterior, campanhas, mensagens proativas, estoque próprio ou do cliente, histórico de compras, reserva, prazo, desconto ou condição negociada. Eles podem ser pedidos pelo representante, mas o assistente deve explicar brevemente que ainda não tem essa informação ou capacidade, sem inventar uma execução.

## Critérios de aceite para a primeira implementação

1. O Gateway classifica separadamente `não entendi` e `entendi, mas não consigo executar`.
2. Apenas o segundo caso cria pendência, e a confirmação da criação precede a promessa de verificação ao cliente.
3. A pendência é idempotente e vinculada ao representante dono da linha de origem, cliente, conversa e mensagem.
4. Na Linha Assistente, representante só vê sua própria carteira e capacidades liberadas pela política vigente.
5. As respostas trazem apenas dados estruturados retornados pelo CRM; o LLM não cria valores ou condições comerciais.
6. A mensagem humana do representante continua tendo prioridade sobre qualquer automação na linha comercial quando essa orquestração for ativada.

## Dependências para ativação

- Contrato Gateway ↔ CRM para criar, consultar e entregar pendências/handoffs.
- Observação de mensagens e autoria na conversa comercial.
- Controle de prioridade humana, concorrência e cancelamento de resposta do bot.
- Definição de retenção de conteúdo conversacional e aprovação de templates Meta para mensagens iniciadas fora da janela aplicável.
