"""Composição do artigo por fibra.

Duas regras moldam este módulo, e as duas vêm do ADR-027.

**A composição é um conjunto que fecha 100%.** Por isso a escrita substitui a
composição inteira em vez de remendar linha a linha: atualizar aos poucos
deixaria estados intermediários inválidos visíveis dentro da transação, e a
validação de soma não teria momento definido para rodar.

**Ausência não é negativa.** Artigo sem composição é artigo cujo cadastro ainda
não foi feito, não artigo sem aquela fibra. `products_by_fiber` devolve os dois
conjuntos separados, e nunca esconde o segundo — quem perguntou por poliéster
precisa ver o que ainda não foi classificado, ou o cadastro incompleto vira
resposta errada com cara de resposta certa.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from crm_api.models.catalog import Product
from crm_api.models.textile import Fiber, ProductComposition
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.textile import TextileRepository

# Fibras que o tenant reconhece de partida. Siglas do setor: é assim que a
# planilha chega, e casar por elas evita uma tabela de tradução.
SEED_FIBERS: tuple[tuple[str, str], ...] = (
    ("PES", "Poliéster"),
    ("CV", "Viscose"),
    ("CO", "Algodão"),
    ("PUE", "Elastano"),
    ("PA", "Poliamida"),
    ("EL", "Elastodieno"),
)

_CEM = Decimal("100")


class CompositionDoesNotSumToHundred(Exception):
    """A soma dos percentuais não fecha 100%."""

    def __init__(self, total: Decimal) -> None:
        self.total = total
        super().__init__(f"composition sums to {total}, expected 100")


class UnknownFiber(Exception):
    """Sigla de fibra que não está cadastrada neste tenant."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"unknown fiber code: {code}")


class DuplicateFiberInComposition(Exception):
    """A mesma fibra aparece duas vezes na composição enviada."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"fiber repeated in composition: {code}")


class ProductNotFound(Exception):
    """Artigo inexistente neste tenant."""


class InvalidPercent(Exception):
    """Percentual fora de (0, 100]."""

    def __init__(self, code: str, percent: Decimal) -> None:
        self.code = code
        self.percent = percent
        super().__init__(f"invalid percent for {code}: {percent}")


@dataclass(frozen=True)
class FiberShare:
    """Uma fibra e o quanto ela ocupa do artigo."""

    fiber: Fiber
    percent: Decimal


@dataclass
class FiberSearchResult:
    """Resposta de `products_by_fiber`, com os dois conjuntos separados.

    `confirmed` são artigos com composição cadastrada que atendem ao filtro.
    `unclassified` são artigos ativos **sem composição nenhuma** — eles podem ou
    não ter a fibra, e o sistema não sabe. Nunca são omitidos.
    """

    confirmed: list[tuple[Product, Decimal]] = field(default_factory=list)
    unclassified: list[Product] = field(default_factory=list)


class TextileService:
    def __init__(self, *, textile: TextileRepository, audit: AuditRepository) -> None:
        self._textile = textile
        self._audit = audit

    # ------------------------------------------------------------------ seed

    async def seed_fibers(self, *, tenant_id: uuid.UUID) -> list[Fiber]:
        """Cadastra as fibras que faltam. Rodar de novo não duplica nem apaga.

        Idempotente pela sigla: o que já existe é deixado como está, inclusive
        se alguém tiver corrigido o nome. O seed semeia, não normaliza.
        """
        existentes = {
            fibra.code: fibra
            for fibra in await self._textile.list_fibers(tenant_id, active=None)
        }
        criadas: list[Fiber] = []
        for code, name in SEED_FIBERS:
            if code in existentes:
                continue
            fibra = Fiber(id=uuid.uuid4(), tenant_id=tenant_id, code=code, name=name)
            self._textile.add(fibra)
            criadas.append(fibra)
        if criadas:
            await self._textile.flush()
        return criadas

    # ------------------------------------------------------------- composição

    async def set_composition(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        shares: list[tuple[str, Decimal]],
        actor_user_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> list[FiberShare]:
        """Substitui a composição inteira do artigo.

        Valida antes de apagar: uma composição recusada não pode deixar o artigo
        sem a que ele tinha. Lista vazia limpa a composição — é como se desfaz um
        cadastro errado, e volta a ser "não classificado", não "sem fibra".
        """
        artigo = await self._textile.get_product(tenant_id, product_id)
        if artigo is None:
            raise ProductNotFound

        resolvidas = await self._resolver(tenant_id, shares)

        anterior = [
            {"code": fibra.code, "percent": str(linha.percent)}
            for linha, fibra in await self._textile.composition_of(tenant_id, product_id)
        ]
        await self._textile.clear_composition(tenant_id, product_id)
        for fibra, percent in resolvidas:
            self._textile.add(
                ProductComposition(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    product_id=product_id,
                    fiber_id=fibra.id,
                    percent=percent,
                )
            )
        await self._textile.flush()

        self._audit.record(
            action="PRODUCT_COMPOSITION_SET",
            entity="product_compositions",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=product_id,
            before={"composition": anterior} if anterior else None,
            after={
                "sku": artigo.sku,
                "composition": [
                    {"code": fibra.code, "percent": str(percent)}
                    for fibra, percent in resolvidas
                ],
            },
            request_id=request_id,
        )
        return [FiberShare(fiber=fibra, percent=percent) for fibra, percent in resolvidas]

    async def _resolver(
        self, tenant_id: uuid.UUID, shares: list[tuple[str, Decimal]]
    ) -> list[tuple[Fiber, Decimal]]:
        """Valida as três coisas que podem estar erradas, na ordem que ajuda.

        Sigla desconhecida primeiro, porque é o erro de digitação mais comum e
        apontar a linha é mais útil do que reclamar da soma. Depois o percentual
        de cada linha. Só então a soma, que é a única que exige o conjunto todo.
        """
        if not shares:
            return []

        vistos: set[str] = set()
        pares: list[tuple[Fiber, Decimal]] = []
        for code, percent in shares:
            canonico = code.strip().upper()
            if canonico in vistos:
                raise DuplicateFiberInComposition(canonico)
            vistos.add(canonico)

            fibra = await self._textile.find_fiber_by_code(tenant_id, canonico)
            if fibra is None or not fibra.active:
                raise UnknownFiber(canonico)
            if percent <= 0 or percent > _CEM:
                raise InvalidPercent(canonico, percent)
            pares.append((fibra, percent))

        total = sum((percent for _, percent in pares), Decimal("0"))
        if total != _CEM:
            raise CompositionDoesNotSumToHundred(total)
        return pares

    async def composition_of(
        self, *, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> list[FiberShare]:
        return [
            FiberShare(fiber=fibra, percent=linha.percent)
            for linha, fibra in await self._textile.composition_of(tenant_id, product_id)
        ]

    # ---------------------------------------------------------------- consulta

    async def products_by_fiber(
        self,
        *,
        tenant_id: uuid.UUID,
        fiber_code: str,
        min_percent: Decimal | None = None,
    ) -> FiberSearchResult:
        """Artigos que contêm a fibra, e os que ninguém classificou ainda.

        Os dois conjuntos vêm separados de propósito. Devolver só o primeiro
        transformaria cadastro incompleto em resposta errada: "não temos
        poliéster" quando na verdade é "ninguém cadastrou ainda".
        """
        fibra = await self._textile.find_fiber_by_code(tenant_id, fiber_code)
        if fibra is None:
            raise UnknownFiber(fiber_code.strip().upper())

        return FiberSearchResult(
            confirmed=await self._textile.products_with_fiber(
                tenant_id, fibra.id, min_percent=min_percent
            ),
            unclassified=await self._textile.products_without_composition(tenant_id),
        )
