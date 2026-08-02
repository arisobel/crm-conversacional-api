# Backlog — Representante multiempresa

## Objetivo

Evoluir o CRM Conversacional API para que uma organização de representantes
administre relacionamento comercial com mais de uma empresa representada, sem
misturar catálogo, preços, ofertas, clientes ou conversas entre empresas.

Este documento é de descoberta e planejamento. Não altera ainda o DDL, os
contratos OpenAPI ou o comportamento do Gateway.

## Decisão de vocabulário a confirmar

| Conceito | Papel no domínio |
|---|---|
| Organização do representante | Workspace, usuários internos e governança do representante. |
| Empresa representada | Dona do catálogo, preços, condições e identidade comercial. |
| Representação comercial | Vínculo com vigência, status e permissões entre organização e empresa. |
| Cliente comprador | Entidade comercial que pode se relacionar com mais de uma empresa representada. |
| Contato | Pessoa e telefone usados no canal; seu vínculo comercial depende da empresa. |
| Canal WhatsApp | Linha e fluxo que determinam o contexto comercial da conversa. |

O `tenant` existente deve manter isolamento comercial enquanto a decisão não
for formalizada. Não deve ser reutilizado implicitamente para significar tanto
representante quanto empresa.

## Princípios não negociáveis

- Uma empresa nunca consulta catálogo, preço, oferta ou conversa de outra.
- O mesmo telefone pode estar associado a clientes de empresas diferentes;
  a linha e o fluxo devem resolver a empresa antes de buscar dados.
- A LLM não escolhe empresa, preço, desconto ou autorização comercial.
- Toda oferta registra empresa representada, organização intermediadora,
  cliente e versão das condições utilizadas.
- Operadores enxergam apenas empresas concedidas à sua organização e papel.

## Backlog priorizado

### MC-001 — ADR de tenancy e isolamento `P0`

- Definir formalmente se `tenant` passa a significar `empresa_representada`.
- Registrar chaves de isolamento em cada agregado e a política de acesso.
- Definir retenção e visibilidade de conversas e eventos.
- Aceite: decisão aprovada antes de qualquer migração de dados.

### MC-002 — Modelo de organização e representação `P0`

- Criar, no modelo lógico, organização do representante, usuário interno,
  empresa representada e vínculo de representação.
- Incluir status, vigência e papéis mínimos.
- Aceite: uma organização pode atender duas empresas sem compartilhamento de
  catálogo ou preços.

### MC-003 — Cliente global e relacionamento comercial `P0`

- Separar a identidade do cliente comprador de seu relacionamento com cada
  empresa representada quando necessário.
- Revisar a unicidade atual de `customer_contacts(tenant_id, whatsapp_e164)`.
- Aceite: o mesmo E.164 pode resolver clientes distintos em contextos de
  empresas diferentes, sem ambiguidade no canal.

### MC-004 — Resolução de empresa pelo Gateway `P0`

- Formalizar o contexto mínimo enviado pelo Gateway: linha, fluxo, canal e
  identificador de empresa autorizada.
- Rejeitar eventos sem empresa resolvida; não inferir empresa por texto livre.
- Aceite: toda chamada comercial é auditável pelo contexto de linha e fluxo.

### MC-005 — Migração e contratos versionados `P1`

- Planejar migrações PostgreSQL reversíveis e backfill, se houver dados.
- Versionar OpenAPI e manifestos de capacidades quando incluírem empresa.
- Aceite: consumidores antigos recebem erro controlado ou rota compatível.

### MC-006 — Administração e auditoria `P1`

- Listar empresas representadas, usuários, vínculos, canais e clientes por
  contexto comercial.
- Registrar criação, alteração de vínculo, troca de empresa e envio de oferta.
- Aceite: administrador explica qual empresa autorizou cada oferta enviada.

### MC-007 — Piloto com duas empresas `P1`

- Configurar duas empresas, seus catálogos e um cliente/telefone em comum.
- Validar busca, preço, oferta e envio pelo WhatsApp.
- Aceite: testes de isolamento impedem leituras cruzadas e o fluxo registra a
  empresa correta em todos os eventos.

## Fora deste incremento

- Migração automática do DDL atual.
- Troca do Gateway por outro roteador.
- Escolha de empresa por LLM.
- Negociação ou aprovação comercial autônoma.
