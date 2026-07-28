# AGENT SKILL ORCHESTRATION

> Camada operacional da migracao `system_remote` -> `pwa-fair`.
> Este arquivo nao substitui `AGENT_SKILL_MIGRATION.md`; ele define como o
> trabalho deve ser coordenado, registrado e retomado sem fragmentar a verdade.

---

## Papel deste arquivo

`AGENT_SKILL_MIGRATION.md` e o contrato de migracao: dominio, fases, trilhas,
regras e equivalencia com `arisobel/system_remote`.

`AGENT_SKILL_ORCHESTRATION.md` e o controle de execucao: o que ler antes de agir,
onde registrar progresso, como ordenar backlog, e quais decisoes precisam ficar
rastreaveis.

---

## Fontes unicas de controle

Toda tarefa de implementacao deve manter estas fontes atualizadas:

| Funcao | Arquivo |
|---|---|
| Progresso central | `docs/00_meta/07_progress.md` |
| Backlog priorizado | `docs/00_meta/09_backlog.md` |
| Decisoes rastreaveis | `docs/00_meta/08_decisions_log.md` |
| Problemas reais conhecidos | `docs/00_meta/KNOWN_ISSUES.md` |
| Manifesto de produto | `docs/00_meta/BUSINESS_FEATURE_MANIFESTO.md` |
| Roadmap MVP | `docs/00_meta/MVP_ROADMAP.md` |

Nao criar novos arquivos para progresso, backlog, decisoes ou issues sem antes
consolidar nesses arquivos.

---

## Loop operacional obrigatorio

Antes de qualquer implementacao:

1. Ler `docs/00_meta/07_progress.md`
2. Ler `docs/00_meta/09_backlog.md`
3. Ler `docs/00_meta/BUSINESS_FEATURE_MANIFESTO.md`
4. Ler `docs/00_meta/MVP_ROADMAP.md`
5. Ler `docs/00_meta/AGENT_SKILL_MIGRATION.md`
6. Ler o blueprint da fase ativa em `docs/40_phases/`, quando aplicavel

Durante a implementacao:

1. Preservar as regras de negocio em `docs/20_concept/BUSINESS_RULES.md`
2. Preservar os contratos em `docs/30_design/API_CONTRACT.md`
3. Registrar qualquer decisao nova em `08_decisions_log.md`
4. Registrar problemas reais em `KNOWN_ISSUES.md`

Apos qualquer mudanca relevante:

1. Atualizar o estado em `07_progress.md`
2. Mover ou remover itens concluidos em `09_backlog.md`
3. Adicionar decisao em `08_decisions_log.md`, se houver tradeoff ou divergencia

---

## Orquestracao paralela com a migracao

A orquestracao trabalha em paralelo com a migracao desta forma:

- `AGENT_SKILL_MIGRATION.md` define trilhas tecnicas e compatibilidade com o sistema de origem.
- `BUSINESS_FEATURE_MANIFESTO.md` define o norte de produto da equipe de negocio.
- `MVP_ROADMAP.md` define o que entra no MVP e o que fica pos-MVP.
- `07_progress.md` aponta a fase ativa e o estado real da execucao.
- `09_backlog.md` transforma o roadmap em proximas acoes.
- `08_decisions_log.md` registra desvios controlados em relacao ao `system_remote`.
- `KNOWN_ISSUES.md` guarda apenas problemas observados no codigo, testes ou produto.

Se houver conflito entre migracao tecnica e manifesto de produto, registrar a
decisao em `08_decisions_log.md` antes de implementar.

---

## Prioridade atual

O foco atual e transformar a migracao em uma **Biblioteca de Tecidos Digital**
operacional. Fair Collection continua sendo a primeira area critica, mas o MVP
tambem precisa explicitar feira, usuarios, nucleos, RBAC basico, galeria de
fotos, busca visual e flows de avaliacao/selecao.

Referencias de origem:

- `arisobel/system_remote/docs/README_fair.md`
- `arisobel/system_remote/docs/README_api.md`
- `arisobel/system_remote/docs/README_business_logic.md`
- `arisobel/system_remote/controllers/samples.py`

Critérios operacionais principais:

- fluxo mobile-first em feira;
- cadastro e escopo por feira;
- usuarios, nucleos e RBAC basico;
- galeria multi-foto por amostra;
- busca visual e filtros evidentes;
- criacao rapida de amostra por fornecedor;
- persistencia offline progressiva;
- sincronizacao sem perda de dados;
- nenhuma duplicacao de fonte de verdade documental.

---

## Regra de compatibilidade Fair Collection

No modo Fair Collection, velocidade de campo prevalece sobre validacoes
administrativas rigidas. A criacao de amostra deve aceitar o minimo necessario
para preservar contexto operacional:

- `fair_id`
- `supplier_id`
- `sample_origin = 2`
- `sample_flow = 4`

Campos como `item_no`, `article_name`, composicao e preco podem ser preenchidos
depois, desde que o registro fique rastreavel e sincronizavel.

---

## Anti-padroes

- Duplicar progresso em docs diferentes.
- Implementar codigo sem atualizar progresso/backlog.
- Criar outro roadmap fora de `MVP_ROADMAP.md` e `09_backlog.md`.
- Tratar o `system_remote` como codigo a copiar literalmente; o alvo e preservar
  logica de fluxo e objetivos administrativos, melhorando velocidade e offline.
