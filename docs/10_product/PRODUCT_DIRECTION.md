# Direção do produto: assistente comercial do representante

> Proposta de 2026-10-12, pendente de aprovação.
> Substitui o [REPRESENTATIVE_DIRECTION.md](REPRESENTATIVE_DIRECTION.md), que
> passa a ser referência histórica. Decisões formais: ADR-031 e ADR-032 em
> [log de decisões](../00_meta/08_decisions_log.md).

## Tese

**Representante organizado vende mais.** O produto é um secretário comercial
para o representante. Ele atende e pré-qualifica os clientes no WhatsApp do
próprio representante enquanto ele está ocupado com outros, e devolve a
conversa ao representante no momento certo, na mesma linha.

A peça técnica que torna isso possível é o **WhatsApp Coexistence**: a mesma
linha é atendida pelo robô e pelo representante no app, sem trocar de número.

## Para quem é

| Persona | O que quer |
|---|---|
| **Representante independente** (cliente principal) | Atender mais clientes com menos esforço, prospectar uma pasta nova, ter a carteira organizada |
| Cliente comprador | Saber o preço dos produtos que costuma comprar, rápido, sem esperar o representante |
| Representada grande (fase futura) | Equipar os próprios representantes com a ferramenta e distribuir a tabela de uma vez |

## Monetização: duas frentes

1. **Representante independente:** maior valor por usuário. É com ele que se
   descobrem e resolvem os problemas reais, que depois se mostram comuns a
   todos.
2. **Representada grande (ex.: Avanti):** menor valor por usuário, com muitos
   representantes. Ela patrocina as licenças e publica a tabela uma vez para
   todos eles.

Ter as duas frentes pulveriza a receita e reduz a dependência de um único
cliente. **A ordem é primeiro o representante.** A frente da representada
entra como camada acima do tenant (ADR-031, "porta aberta") e não exige mudar o
modelo de agora. Indício de mercado: cerca de metade dos representantes de fios
da Avanti também vende tinturaria, ou seja, as mesmas representadas aparecem
em muitos representantes.

## Modelo

```
Tenant = escritório de representação (pode ser uma pessoa)
 ├─ Usuários: representantes e admin
 ├─ Linha WhatsApp por representante (Coexistence)
 ├─ Representadas (pastas): Avanti fios, tinturaria, legging...
 │    ├─ Observação comercial opcional
 │    ├─ Produtos ou serviços (unidade livre; atributos têxteis opcionais)
 │    └─ Tabela por competência = preço final informado pelo representante
 └─ Clientes
      ├─ Titular (um por cliente)
      ├─ Pastas com que trabalha (N:N)
      └─ Produtos preferidos (podem misturar pastas)
```

## Princípios

- **O preço é o do representante.** Nenhum imposto é calculado no caminho
  padrão (ADR-032).
- **A carteira manda.** O robô só fala com cliente cujo titular é o dono da
  linha. Fora disso, silêncio (já está em produção).
- **O representante tem a última palavra.** Nada sai de forma ativa sem
  aprovação. Pergunta fora do escopo (imposto, negociação) vai para ele.
- **Flexível antes de completo.** Abrir uma pasta nova tem de ser simples:
  cadastrar a representada, subir a tabela, marcar os clientes.
- **Genérico por baixo, têxtil por cima.** O núcleo serve a qualquer vendedor.
  O têxtil é a primeira especialização.
- O LLM nunca produz preço, nem escolhe cliente ou pasta (princípios
  anteriores mantidos).

## Jornadas do primeiro corte

### 1. O cliente chama (reativo)

> **Cliente:** oi
> **Robô:** Olá, Argotex! Quer saber o preço de hoje dos seus produtos?
> 75/36 urdume · 150/48 trama · Tingimento preto
> [Sim] [Outro produto]
> **Cliente:** Sim
> **Robô:** (lista os preços da tabela vigente de cada pasta, com a
> observação da pasta, se houver) Qual quantidade você precisa?
> **Cliente:** 500 kg do 75/36
> → **o representante é avisado** e assume a conversa pelo app.

Se o cliente digitar um artigo ("55/36"), o robô **primeiro confirma** qual é
("Você quer o 55/36 trama, que costuma comprar?") e só então mostra o preço.
A busca prioriza os preferidos e os apelidos do cliente.

### 2. O representante prospecta (ativo)

O representante escolhe uma pasta, ou os preferidos de cada cliente, e o
público. O sistema monta as mensagens, **ele aprova**, e o envio sai pelo
número dele, com um modelo aprovado pela Meta e botões
(Sim / Não / Semana que vem). "Semana que vem" agenda uma nova tentativa. O
"Sim" leva à jornada 1.

## Ordem de entrega proposta

| # | Entrega | Depende de |
|---|---|---|
| 1 | Integridade da carteira (F4) e silêncio completo (F2) | Já planejadas |
| 2 | Preço sem imposto no fluxo padrão (ADR-032) | Nada |
| 3 | Jornada 1: saudação com preferidos, [Sim], confirmação do artigo, aviso ao representante | 2 |
| 4 | Representadas (pastas) e vínculo cliente × pasta (ADR-031) | 2 |
| 5 | Jornada 2: prospecção com aprovação e template | 3 e 4; campanhas F6 |
| 6 | Conversa híbrida completa (F7: passagem para o humano e retorno do robô) | 3 |

## Questões em aberto (não bloqueiam o primeiro corte)

- Titular por pasta dentro de um escritório com vários representantes.
- Formato da tabela de serviços (tinturaria): pedir um exemplo real.
- Quem carrega a tabela de cada pasta. Hipótese: o próprio representante, por
  planilha ou PDF, com revisão antes de publicar (ADR-009).
- Como o representante é avisado do "Sim + quantidade": WhatsApp, portal ou
  ambos.
- Preço do produto para as duas frentes de monetização.
