# Backlog — Interface administrativa do CRM

> **Absorvido em 2026-08-04 por [F5 — portal do representante](F5_REPRESENTATIVE_PORTAL.md).**
> As fases deste documento foram redistribuídas: A → R0, B → R1 e R2, C → R6,
> D → R3, E permanece adiada. O painel deixa de ser "administrativo" e passa a
> ser o portal operado por representantes, com escopo de carteira. O ADR-011
> continua válido: a interface é cliente da API, nunca do PostgreSQL. Este
> documento permanece como referência dos requisitos originais.

## Objetivo

Eliminar a dependência de SQL manual e terminal para manter clientes, contatos, catálogo e
tabelas de preço. A interface é uma aplicação interna autenticada, cliente da API CRM e
nunca cliente direto do PostgreSQL.

## Limite entre CRM e Gateway

| Responsabilidade | Sistema dono |
|---|---|
| Empresa cliente, documento, UF, contato e telefone | CRM |
| Família, produto, SKU, especificação e tabela de preço | CRM |
| Importação, revisão e ativação de tabela | CRM |
| Aplicativo, fluxo, linha Meta e autorização de telefone | Gateway / `whatsapp_control` |
| Envio e recebimento WhatsApp | Gateway |

O cadastro de um novo cliente ocorre primeiro no CRM. O Gateway não deve criar cliente
nem acessar o banco CRM. Para que o novo telefone use o fluxo, é necessária também uma
autorização no Gateway. Inicialmente, isso pode ocorrer na tela administrativa já existente
do Gateway; em etapa posterior, o CRM poderá solicitar essa autorização por uma API interna
idempotente e auditável do Gateway, sem acessar o MySQL diretamente.

## Fase A — Fundamentos de administração

- Autenticação interna, sessão segura e perfis `ADMIN` e `COMERCIAL`.
- Auditoria imutável de criação, edição, ativação e desativação.
- Escopo obrigatório de tenant em toda operação.
- Endpoints administrativos separados das consultas internas HMAC do Gateway.
- Interface server-rendered ou SPA simples; a escolha não altera o contrato da API.

## Fase B — Clientes e contatos

- Listar e pesquisar clientes por razão social, fantasia, documento, UF e telefone.
- Criar/editar/desativar cliente.
- Criar/editar/desativar contatos, com validação E.164 e indicação de contato principal.
- Mostrar o estado de autorização WhatsApp: `não autorizado`, `pendente` ou `autorizado`.
- Salvar cliente no CRM e, opcionalmente, abrir a autorização de telefone no Gateway.

## Fase C — Catálogo e preferências

- CRUD de famílias e produtos com SKU único, especificação e unidade.
- Ativação/desativação lógica de catálogo.
- Produtos preferenciais, alias e ordem por cliente.
- Prévia da linguagem que o WhatsApp exibirá para cada produto.

## Fase D — Tabelas de preço

- Upload de CSV e prévia antes de persistir.
- Relatório de linhas inválidas, SKU duplicado, preço ausente e disponibilidade incoerente.
- Revisão humana de itens em `DRAFT`.
- Ativação explícita por usuário autorizado, impedindo sobreposição de tabelas ativas.
- Histórico de importação, ativação e autor responsável.

## Fase E — Configuração conversacional CRM

- Tela para aliases, exemplos, mensagens de ajuda e versão do manifesto de capacidades.
- Validação declarativa: somente intenções e ações permitidas pelo CRM.
- Publicação versionada; a versão nova passa a valer quando a sessão Gateway expirar.
- Auditoria de alteração e possibilidade de restaurar versão anterior.

## Integração CRM → Gateway posterior

A integração única de cadastro será desenhada somente após as fases B e E estarem
operacionais. Ela deve usar uma API administrativa dedicada do Gateway, autenticação entre
serviços, chave de idempotência e auditoria nos dois lados. Se a autorização falhar, o
cliente continua válido no CRM e a interface mostra ação pendente; não haverá rollback do
cadastro comercial.

## Critérios de aceite iniciais

- Um usuário administrativo cria cliente e contato sem SQL.
- Telefone inválido ou duplicado é rejeitado antes de salvar.
- O usuário visualiza que o contato ainda precisa ser autorizado no Gateway.
- Nenhuma credencial PostgreSQL é exposta ao navegador ou à interface.
- Ativação de tabela deixa rastreabilidade de usuário, data e versão.
