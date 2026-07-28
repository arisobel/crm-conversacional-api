# Escopo do MVP

## Objetivo

Gerar e registrar ofertas comerciais personalizadas para clientes via WhatsApp, usando produtos preferenciais, tabela vigente e regras comerciais auditáveis.

## Caso inicial

Para um contato identificado pelo número do WhatsApp:

1. localizar cliente e UF de destino;
2. carregar seus produtos preferenciais;
3. obter a tabela vigente;
4. calcular preço a prazo e antecipado;
5. aplicar frete, imposto e disponibilidade;
6. gerar a prévia textual;
7. obter confirmação humana;
8. enviar pelo Gateway;
9. preservar exatamente o que foi enviado.

## Critérios de sucesso

- Um evento repetido não gera processamento duplicado.
- Nenhum preço é produzido pela LLM.
- Toda oferta enviada possui itens imutáveis e auditáveis.
- Valores monetários usam `numeric`, nunca ponto flutuante.
- Uma tabela mensal é consultável sem criar novas tabelas físicas.
- O contato e o cliente são identificáveis por telefone E.164.
