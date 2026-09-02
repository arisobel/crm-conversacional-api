"""Resolvedor determinístico de audiência de campanha (F6.2, ADR-028).

Três regras governam este módulo, e as três são recusas:

**Nada é inferido.** Os critérios chegam estruturados e fechados. Um eixo que o
domínio não modela — porte, curva ABC, potencial — produz erro orientado ao
usuário, nunca um público "plausível". `AudienceCriteria.from_mapping` recusa
chave desconhecida em vez de ignorá-la, porque ignorar é a forma silenciosa de
montar o alvo errado.

**Nada some sem explicação.** Um cliente da carteira que casa com o critério
mas não pode receber não desaparece da prévia: ele volta como exclusão, com
motivo acionável. Público que encolhe sem dizer por quê é o defeito que esta
fase existe para impedir.

**Ausência de dado não vira negativa.** Cliente cujos artigos preferidos não
têm composição cadastrada não é "cliente sem poliéster": é cliente sobre quem
não dá para afirmar nada. Ele sai num terceiro balde — `unclassified` — que não
vira destinatário e não é contado como exclusão comercial (ADR-027).

A ordem de filtragem é a do plano F6 e não é negociável: tenant, papel e
usuário, carteira, ativos, filtros comerciais. O consentimento é o sexto passo
e **não existe aqui** — ele é do Gateway e entra na F6.4.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from crm_api.models.customer import Customer
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import UserRole
from crm_api.repositories.campaign_audience import AudienceRepository
from crm_api.services.whatsapp_campaign import DraftRecipient

# Motivos de exclusão. Constantes, e não texto solto no lugar de uso, porque a
# tela agrupa por motivo e a auditoria compara — duas grafias do mesmo motivo
# viram duas linhas no relatório.
SEM_CONTATO_ATIVO = "SEM_CONTATO_ATIVO"
CONTATO_AMBIGUO = "CONTATO_AMBIGUO"

# Eixos que o domínio modela hoje. Qualquer outra chave é recusada.
EIXOS_CONHECIDOS = frozenset(
    {
        "product_group_ids",
        "fiber_codes",
        "min_fiber_percent",
        "product_ids",
        "state_codes",
        "include_entire_portfolio",
    }
)

# Eixos pedidos pelo negócio que ainda não existem como atributo. Merecem
# mensagem própria: "não existe" é menos útil que "ainda não foi modelado".
EIXOS_NAO_MODELADOS = {
    "porte": "porte ainda não é atributo do cliente; ele precisa ser declarado"
    " antes de virar filtro (D1)",
    "curva_abc": "curva ABC não é atributo do cliente e não pode ser inferida"
    " de compra ou volume",
    "potencial": "potencial de crescimento não é atributo do cliente e não pode"
    " ser inferido",
    "lista_julgamento": "listas de julgamento ainda não foram modeladas; a"
    " visibilidade delas é pendência da F6.0",
}


class UnknownCriterion(ValueError):
    """Um eixo que o domínio não modela. A mensagem é orientada ao usuário."""


class EmptyCriteria(ValueError):
    """Nenhum critério informado.

    Não é o mesmo que "toda a carteira": mandar para todo mundo é escolha
    explícita, feita com `include_entire_portfolio`, e não o que sobra de um
    formulário vazio.
    """


class UnknownProductGroup(ValueError):
    """Grupo pedido não existe ou está inativo neste tenant."""


class UnknownFiber(ValueError):
    """Sigla de fibra não cadastrada neste tenant."""


class UnknownProduct(ValueError):
    """Artigo pedido não existe ou está inativo neste tenant."""


@dataclass(frozen=True)
class AudienceCriteria:
    """Critérios estruturados. Nenhum campo aceita texto livre interpretável.

    Semântica de combinação, fixada aqui porque precisa ser previsível:

    - **Dentro de um eixo, os valores somam (OU).** Dois grupos trazem os
      artigos de qualquer um dos dois.
    - **Entre eixos de produto, eles se cruzam (E).** Grupo "alta-tenacidade"
      mais fibra `PES` significa os artigos que são as duas coisas — não a
      soma dos dois conjuntos.
    - **`state_codes` é eixo de cliente**, aplicado depois, também com E.
    """

    product_group_ids: tuple[uuid.UUID, ...] = ()
    fiber_codes: tuple[str, ...] = ()
    min_fiber_percent: Decimal | None = None
    product_ids: tuple[uuid.UUID, ...] = ()
    state_codes: tuple[str, ...] = ()
    include_entire_portfolio: bool = False

    @property
    def tem_eixo_de_produto(self) -> bool:
        return bool(self.product_group_ids or self.fiber_codes or self.product_ids)

    @classmethod
    def from_mapping(cls, raw: dict) -> "AudienceCriteria":
        """Constrói a partir de um mapa, recusando o que não for modelado.

        É aqui que a regra "não inferir" vira código: uma chave desconhecida
        levanta erro em vez de ser descartada em silêncio, e os eixos que o
        negócio já pediu e ainda não existem têm mensagem própria.
        """
        if not isinstance(raw, dict):
            raise UnknownCriterion("os critérios precisam vir estruturados")

        for chave in raw:
            if chave in EIXOS_NAO_MODELADOS:
                raise UnknownCriterion(EIXOS_NAO_MODELADOS[chave])
            if chave not in EIXOS_CONHECIDOS:
                raise UnknownCriterion(
                    f"critério desconhecido: {chave!r}. "
                    f"Eixos disponíveis: {', '.join(sorted(EIXOS_CONHECIDOS))}"
                )

        percentual = raw.get("min_fiber_percent")
        if percentual is not None:
            try:
                percentual = Decimal(str(percentual))
            except (InvalidOperation, ValueError) as erro:
                raise UnknownCriterion(
                    "min_fiber_percent precisa ser um número"
                ) from erro
            if percentual <= 0 or percentual > 100:
                raise UnknownCriterion("min_fiber_percent precisa estar entre 0 e 100")

        criterios = cls(
            product_group_ids=tuple(raw.get("product_group_ids") or ()),
            fiber_codes=tuple(
                code.strip().upper()
                for code in (raw.get("fiber_codes") or ())
                if code and code.strip()
            ),
            min_fiber_percent=percentual,
            product_ids=tuple(raw.get("product_ids") or ()),
            state_codes=tuple(
                uf.strip().upper()
                for uf in (raw.get("state_codes") or ())
                if uf and uf.strip()
            ),
            include_entire_portfolio=bool(raw.get("include_entire_portfolio", False)),
        )

        if criterios.min_fiber_percent is not None and not criterios.fiber_codes:
            raise UnknownCriterion(
                "min_fiber_percent só faz sentido junto de fiber_codes"
            )
        if not (
            criterios.tem_eixo_de_produto
            or criterios.state_codes
            or criterios.include_entire_portfolio
        ):
            raise EmptyCriteria(
                "informe ao menos um critério; para alcançar toda a carteira use"
                " include_entire_portfolio"
            )
        return criterios

    def normalized(self) -> dict:
        """Forma canônica que vai para o `criteria_snapshot` do rascunho.

        Ordenada e sem chave vazia: dois pedidos equivalentes produzem o mesmo
        dicionário, e é ele que explica seis meses depois o que foi aprovado.
        """
        saida: dict = {}
        if self.product_group_ids:
            saida["product_group_ids"] = sorted(str(i) for i in self.product_group_ids)
        if self.fiber_codes:
            saida["fiber_codes"] = sorted(self.fiber_codes)
        if self.min_fiber_percent is not None:
            saida["min_fiber_percent"] = str(self.min_fiber_percent)
        if self.product_ids:
            saida["product_ids"] = sorted(str(i) for i in self.product_ids)
        if self.state_codes:
            saida["state_codes"] = sorted(self.state_codes)
        if self.include_entire_portfolio:
            saida["include_entire_portfolio"] = True
        return saida


@dataclass(frozen=True)
class AudienceMember:
    """Um cliente na prévia, elegível ou excluído — nunca omitido."""

    customer: Customer
    contact: CustomerContact | None = None
    excluded_reason: str | None = None

    @property
    def eligible(self) -> bool:
        return self.excluded_reason is None


@dataclass(frozen=True)
class AudiencePreview:
    normalized_criteria: dict
    eligible: list[AudienceMember] = field(default_factory=list)
    excluded: list[AudienceMember] = field(default_factory=list)
    # Terceiro balde: casaria pelo eixo de fibra, mas o artigo preferido não
    # tem composição cadastrada. Não é exclusão comercial — é lacuna de
    # cadastro, e some da prévia assim que alguém completar o cadastro.
    unclassified: list[Customer] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {
            "eligible": len(self.eligible),
            "excluded": len(self.excluded),
            "unclassified": len(self.unclassified),
            "total": len(self.eligible) + len(self.excluded),
        }

    def to_draft_recipients(self) -> list[DraftRecipient]:
        """Converte a prévia no público congelável do rascunho (F6.1).

        Os `unclassified` **não** entram: eles não foram julgados, e congelar
        um julgamento que ninguém fez seria inventar o dado que falta.
        """
        return [
            DraftRecipient(
                customer_id=membro.customer.id,
                contact_id=membro.contact.id if membro.contact else None,
                excluded_reason=membro.excluded_reason,
            )
            for membro in (*self.eligible, *self.excluded)
        ]


class AudienceResolver:
    def __init__(self, *, audience: AudienceRepository) -> None:
        self._audience = audience

    async def _produtos_alvo(
        self, tenant_id: uuid.UUID, criterios: AudienceCriteria
    ) -> tuple[set[uuid.UUID] | None, set[uuid.UUID]]:
        """Resolve os eixos de produto em (alvo, não classificados).

        `None` como alvo significa "sem recorte de produto" — diferente de um
        conjunto vazio, que significa "nenhum artigo casou".
        """
        conjuntos: list[set[uuid.UUID]] = []
        nao_classificados: set[uuid.UUID] = set()

        if criterios.product_group_ids:
            pedidos = list(criterios.product_group_ids)
            existentes = await self._audience.existing_group_ids(tenant_id, pedidos)
            faltando = [str(g) for g in pedidos if g not in existentes]
            if faltando:
                raise UnknownProductGroup(
                    f"grupo de artigo inexistente ou inativo: {', '.join(sorted(faltando))}"
                )
            conjuntos.append(await self._audience.products_in_groups(tenant_id, pedidos))

        if criterios.fiber_codes:
            fibras = await self._audience.fibers_by_codes(
                tenant_id, list(criterios.fiber_codes)
            )
            faltando = [c for c in criterios.fiber_codes if c not in fibras]
            if faltando:
                raise UnknownFiber(
                    f"fibra não cadastrada neste tenant: {', '.join(sorted(faltando))}"
                )
            conjuntos.append(
                await self._audience.products_with_fibers(
                    tenant_id,
                    [f.id for f in fibras.values()],
                    min_percent=criterios.min_fiber_percent,
                )
            )
            # Só o eixo de fibra produz "não classificado": grupo é curadoria
            # explícita, e não estar num grupo é um fato, não uma lacuna.
            nao_classificados = await self._audience.products_without_composition(tenant_id)

        if criterios.product_ids:
            pedidos = list(criterios.product_ids)
            existentes = await self._audience.existing_product_ids(tenant_id, pedidos)
            faltando = [str(p) for p in pedidos if p not in existentes]
            if faltando:
                raise UnknownProduct(
                    f"artigo inexistente ou inativo: {', '.join(sorted(faltando))}"
                )
            conjuntos.append(existentes)

        if not conjuntos:
            return None, set()

        alvo = set.intersection(*conjuntos)
        return alvo, nao_classificados

    @staticmethod
    def _escolhe_contato(
        contatos: list[CustomerContact],
    ) -> tuple[CustomerContact | None, str | None]:
        """Política explícita de destinatário: **uma mensagem por cliente**.

        O principal ganha. Sem principal, um único contato ativo é escolha
        inequívoca. Vários ativos sem principal é ambiguidade real — e a saída
        é excluir com motivo acionável, não eleger um por ordem de cadastro:
        o modelo-alvo pede que a política seja explícita justamente para que
        ninguém receba duas vezes nem receba por acaso.
        """
        if not contatos:
            return None, SEM_CONTATO_ATIVO
        principais = [c for c in contatos if c.is_primary]
        if principais:
            return principais[0], None
        if len(contatos) == 1:
            return contatos[0], None
        return None, CONTATO_AMBIGUO

    async def resolve(
        self,
        tenant_id: uuid.UUID,
        raw_criteria: dict,
        *,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
    ) -> AudiencePreview:
        """A prévia reproduzível: mesmos critérios e mesmos dados, mesma saída.

        `actor_role` entra na assinatura e é registrado, mas não amplia
        alcance: a carteira é sempre a de `actor_user_id`, para qualquer papel.
        Ver a nota da F6.0 em `whatsapp_campaign.py`.
        """
        criterios = AudienceCriteria.from_mapping(raw_criteria)
        alvo, produtos_sem_composicao = await self._produtos_alvo(tenant_id, criterios)

        clientes = await self._audience.customers_in_scope(
            tenant_id,
            owner_user_id=actor_user_id,
            state_codes=list(criterios.state_codes) or None,
            preferring_any_of=alvo,
        )

        # Quem não casou pelo alvo, mas prefere artigo sem composição, não é
        # negativa: é indeterminado. Só faz sentido quando houve eixo de fibra.
        indeterminados: list[Customer] = []
        if produtos_sem_composicao:
            ja_incluidos = {c.id for c in clientes}
            candidatos = await self._audience.customers_in_scope(
                tenant_id,
                owner_user_id=actor_user_id,
                state_codes=list(criterios.state_codes) or None,
                preferring_any_of=produtos_sem_composicao,
            )
            indeterminados = [c for c in candidatos if c.id not in ja_incluidos]

        contatos = await self._audience.active_contacts(
            tenant_id, [c.id for c in clientes]
        )

        elegiveis: list[AudienceMember] = []
        excluidos: list[AudienceMember] = []
        for cliente in clientes:
            contato, motivo = self._escolhe_contato(contatos.get(cliente.id, []))
            membro = AudienceMember(
                customer=cliente, contact=contato, excluded_reason=motivo
            )
            (elegiveis if membro.eligible else excluidos).append(membro)

        return AudiencePreview(
            normalized_criteria=criterios.normalized(),
            eligible=elegiveis,
            excluded=excluidos,
            unclassified=indeterminados,
        )
