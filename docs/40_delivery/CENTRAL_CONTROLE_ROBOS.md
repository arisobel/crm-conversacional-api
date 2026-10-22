# Central de controle dos robôs

Proposta de evolução do portal para configurar os robôs por empresa sem exigir
deploy para cada ajuste. A configuração salva só terá efeito quando o Gateway
e os executores passarem a consultá-la; nenhuma tela deve sugerir que uma
configuração ainda não integrada está ativa.

## Primeira entrega: linha assistente

Uma aba restrita a administradores permite habilitar a empresa, habilitar cada
representante e selecionar suas capacidades existentes. Ausência de
configuração significa desabilitado. Alterações devem registrar autor, data e
valores anteriores e novos, com isolamento por empresa e proteção CSRF.
Usuários inativos continuam sem acesso, independentemente da configuração.

O painel deve informar claramente que essas escolhas ainda não controlam o
tráfego até a integração prevista em [política do assistente](ASSISTANT_POLICY_CONTRACT.md).
O manifesto e cada executor precisam revalidar a política, com identidade
confiável de linha e sem fallback permissivo.

## Evolução: atendimento Coexistence

A mesma central pode apresentar uma seção própria para o robô que atende
clientes pela linha comercial, separada da linha assistente. Uma primeira
versão pode permitir editar textos de saudação e ausência, tom de comunicação,
horários e instruções de atendimento dentro de limites definidos. Dados de
preço, carteira, consentimento, autorizações e transferência para atendimento
humano continuam sujeitos às regras determinísticas do sistema.

Antes de implementar controles operacionais, definir com o Gateway quais
campos ele consome, escopo por empresa e linha, valores padrão, validação,
versão publicada, atualização de cache, comportamento em falhas e auditoria.
A interface deve distinguir rascunho, configuração publicada e configuração
efetivamente aplicada, e oferecer prévia e histórico de alterações. A edição de
um texto não deve prometer alteração instantânea sem confirmação do Gateway.

Mudanças de configuração suportadas pelo contrato poderão ser publicadas sem
deploy. Novas capacidades, mudanças de integração ou de regras de segurança
podem continuar exigindo desenvolvimento e implantação.
