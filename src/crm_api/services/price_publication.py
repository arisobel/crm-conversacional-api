"""Publicação de um lote de importação para o preço vigente.

O fluxo do ADR-009 continua: `CSV → lote DRAFT → revisão humana → publicação`.
O que a `0006` mudou é o destino da publicação — os valores são promovidos para
`price_entries`, sob a chave `(tenant, competência, produto)` do ADR-014.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.pricing import (
    PriceEntry,
    PriceEntryRevision,
    PriceList,
    PriceListItem,
    PriceListStatus,
)
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.price_entries import PriceEntryRepository

# Campos que definem se o preço mudou. `display_order` fica de fora de propósito:
# reordenar a apresentação não é uma mudança de preço e não merece revisão.
_CAMPOS_COMPARADOS = (
    "base_price",
    "base_tax_rate",
    "availability",
    "expected_arrival_date",
    "available_quantity_kg",
    "arrival_note",
    "notes",
)


class BatchNotFound(Exception):
    """Lote inexistente no tenant."""


class BatchNotPublishable(Exception):
    """Lote em estado que não admite publicação."""


@dataclass
class PublicationResult:
    reference_month: object
    criados: int = 0
    atualizados: int = 0
    inalterados: int = 0
    produtos_alterados: list[uuid.UUID] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.criados + self.atualizados + self.inalterados


def _instantaneo(entrada: PriceEntry) -> dict:
    """Fotografia comparável e serializável do preço."""
    return {
        "base_price": str(entrada.base_price),
        "base_tax_rate": str(entrada.base_tax_rate) if entrada.base_tax_rate is not None else None,
        "availability": entrada.availability.value,
        "expected_arrival_date": (
            entrada.expected_arrival_date.isoformat()
            if entrada.expected_arrival_date
            else None
        ),
        "available_quantity_kg": (
            str(entrada.available_quantity_kg)
            if entrada.available_quantity_kg is not None
            else None
        ),
        "arrival_note": entrada.arrival_note,
        "notes": entrada.notes,
    }


def _valor_do_item(item: PriceListItem, lote: PriceList, campo: str):
    if campo == "base_tax_rate":
        # A alíquota do item prevalece sobre a do lote; nenhuma das duas é
        # inventada quando ambas faltam.
        return item.item_tax_rate if item.item_tax_rate is not None else lote.base_tax_rate
    return getattr(item, campo)


class PricePublicationService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        entries: PriceEntryRepository,
        audit: AuditRepository,
    ) -> None:
        self._session = session
        self._entries = entries
        self._audit = audit

    async def publish_batch(
        self,
        *,
        tenant_id: uuid.UUID,
        batch_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> PublicationResult:
        lote = await self._session.scalar(
            select(PriceList).where(PriceList.id == batch_id, PriceList.tenant_id == tenant_id)
        )
        if lote is None:
            raise BatchNotFound
        if lote.status in {PriceListStatus.CANCELLED, PriceListStatus.EXPIRED}:
            raise BatchNotPublishable(f"lote em estado {lote.status.value}")

        itens = list(
            await self._session.scalars(
                select(PriceListItem).where(PriceListItem.price_list_id == lote.id)
            )
        )
        resultado = PublicationResult(reference_month=lote.reference_month)
        agora = datetime.now(UTC)

        for item in itens:
            vigente = await self._entries.get(tenant_id, lote.reference_month, item.product_id)

            if vigente is None:
                nova = PriceEntry(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    reference_month=lote.reference_month,
                    product_id=item.product_id,
                    display_order=item.display_order,
                    source_batch_id=lote.id,
                    published_at=agora,
                    published_by=actor_user_id,
                    base_price=Decimal("0"),
                )
                for campo in _CAMPOS_COMPARADOS:
                    setattr(nova, campo, _valor_do_item(item, lote, campo))
                self._entries.add(nova)
                self._registrar_revisao(nova, anterior=None, lote=lote, autor=actor_user_id)
                resultado.criados += 1
                resultado.produtos_alterados.append(item.product_id)
                continue

            anterior = _instantaneo(vigente)
            for campo in _CAMPOS_COMPARADOS:
                setattr(vigente, campo, _valor_do_item(item, lote, campo))
            vigente.display_order = item.display_order

            if _instantaneo(vigente) == anterior:
                # Republicar o mesmo conteúdo é idempotente: sem revisão, para
                # que a trilha continue contando só o que de fato mudou.
                resultado.inalterados += 1
                continue

            vigente.source_batch_id = lote.id
            vigente.published_at = agora
            vigente.published_by = actor_user_id
            self._registrar_revisao(vigente, anterior=anterior, lote=lote, autor=actor_user_id)
            resultado.atualizados += 1
            resultado.produtos_alterados.append(item.product_id)

        lote.status = PriceListStatus.PUBLISHED
        self._audit.record(
            action="PRICE_BATCH_PUBLISHED",
            entity="price_lists",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=lote.id,
            after={
                "reference_month": lote.reference_month.isoformat(),
                "criados": resultado.criados,
                "atualizados": resultado.atualizados,
                "inalterados": resultado.inalterados,
            },
            request_id=request_id,
        )
        return resultado

    def _registrar_revisao(
        self,
        entrada: PriceEntry,
        *,
        anterior: dict | None,
        lote: PriceList,
        autor: uuid.UUID | None,
    ) -> None:
        self._entries.add(
            PriceEntryRevision(
                id=uuid.uuid4(),
                tenant_id=entrada.tenant_id,
                reference_month=entrada.reference_month,
                product_id=entrada.product_id,
                previous=anterior,
                current=_instantaneo(entrada),
                batch_id=lote.id,
                changed_by=autor,
            )
        )
