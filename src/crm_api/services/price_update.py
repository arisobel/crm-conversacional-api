"""Proposta revisável de atualização de preços vinda do WhatsApp."""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import Product
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceEntry,
    PriceList,
    PriceListItem,
    PriceListStatus,
)


class PriceUpdateProposalNotFound(Exception):
    pass


class PriceUpdateProposalForbidden(Exception):
    pass


@dataclass(frozen=True)
class ProposedPriceRow:
    sku: str
    base_price: Decimal


@dataclass(frozen=True)
class PriceChange:
    sku: str
    product_name: str
    previous_price: Decimal | None
    new_price: Decimal
    change: str


@dataclass
class PriceUpdateProposal:
    reference_month: date
    proposal_id: uuid.UUID | None = None
    duplicate_skus: list[str] = field(default_factory=list)
    unknown_skus: list[str] = field(default_factory=list)
    changes: list[PriceChange] = field(default_factory=list)

    @property
    def ready_for_confirmation(self) -> bool:
        return self.proposal_id is not None and not self.duplicate_skus and not self.unknown_skus


def _sku(value: str) -> str:
    return " ".join(value.strip().upper().split())[:120]


class RepresentativePriceUpdateService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def propose(
        self,
        *,
        tenant_id: uuid.UUID,
        representative_user_id: uuid.UUID,
        source_wamid: str,
        reference_month: date,
        rows: list[ProposedPriceRow],
    ) -> PriceUpdateProposal:
        if reference_month.day != 1:
            raise ValueError("reference_month must be the first day of the month")
        existing = await self._session.scalar(
            select(PriceList).where(
                PriceList.tenant_id == tenant_id,
                PriceList.source_wamid == source_wamid,
            )
        )
        if existing is not None:
            if existing.created_by != representative_user_id:
                raise PriceUpdateProposalForbidden
            return await self._describe(existing)

        normalized = [ProposedPriceRow(_sku(row.sku), row.base_price) for row in rows]
        counts: dict[str, int] = {}
        for row in normalized:
            counts[row.sku] = counts.get(row.sku, 0) + 1
        duplicates = sorted(sku for sku, count in counts.items() if count > 1)
        unique_rows = {row.sku: row for row in normalized}
        products = list(
            await self._session.scalars(
                select(Product).where(
                    Product.tenant_id == tenant_id,
                    Product.active.is_(True),
                    func.upper(Product.sku).in_(list(unique_rows)),
                )
            )
        )
        by_sku = {_sku(product.sku): product for product in products}
        unknown = sorted(set(unique_rows) - set(by_sku))
        result = PriceUpdateProposal(
            reference_month=reference_month,
            duplicate_skus=duplicates,
            unknown_skus=unknown,
        )
        if duplicates or unknown:
            return result

        digest = hashlib.sha256(source_wamid.encode("utf-8")).hexdigest()[:16]
        batch = PriceList(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=f"Atualização WhatsApp {digest}",
            reference_month=reference_month,
            valid_from=datetime(reference_month.year, reference_month.month, 1, tzinfo=UTC),
            currency="BRL",
            status=PriceListStatus.DRAFT,
            created_by=representative_user_id,
            source_wamid=source_wamid,
        )
        self._session.add(batch)
        for order, row in enumerate(normalized):
            product = by_sku[row.sku]
            current = await self._session.scalar(
                select(PriceEntry).where(
                    PriceEntry.tenant_id == tenant_id,
                    PriceEntry.reference_month == reference_month,
                    PriceEntry.product_id == product.id,
                )
            )
            previous = current.base_price if current is not None else None
            change = (
                "NEW"
                if previous is None
                else "UNCHANGED"
                if previous == row.base_price
                else "CHANGED"
            )
            result.changes.append(
                PriceChange(
                    sku=product.sku,
                    product_name=product.commercial_name,
                    previous_price=previous,
                    new_price=row.base_price,
                    change=change,
                )
            )
            self._session.add(
                PriceListItem(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    price_list_id=batch.id,
                    product_id=product.id,
                    base_price=row.base_price,
                    availability=current.availability if current else AvailabilityStatus.AVAILABLE,
                    expected_arrival_date=current.expected_arrival_date if current else None,
                    available_quantity_kg=current.available_quantity_kg if current else None,
                    arrival_note=current.arrival_note if current else None,
                    item_tax_rate=current.base_tax_rate if current else None,
                    notes=current.notes if current else None,
                    display_order=current.display_order if current else order,
                )
            )
        await self._session.flush()
        result.proposal_id = batch.id
        return result

    async def get_owned(
        self, tenant_id: uuid.UUID, representative_user_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> PriceList:
        batch = await self._session.scalar(
            select(PriceList).where(
                PriceList.id == proposal_id,
                PriceList.tenant_id == tenant_id,
            )
        )
        if batch is None:
            raise PriceUpdateProposalNotFound
        if batch.created_by != representative_user_id or batch.source_wamid is None:
            raise PriceUpdateProposalForbidden
        return batch

    async def _describe(self, batch: PriceList) -> PriceUpdateProposal:
        items = (
            await self._session.execute(
                select(PriceListItem, Product)
                .join(Product, Product.id == PriceListItem.product_id)
                .where(PriceListItem.price_list_id == batch.id)
                .order_by(PriceListItem.display_order, Product.sku)
            )
        ).all()
        result = PriceUpdateProposal(reference_month=batch.reference_month, proposal_id=batch.id)
        for item, product in items:
            current = await self._session.scalar(
                select(PriceEntry).where(
                    PriceEntry.tenant_id == batch.tenant_id,
                    PriceEntry.reference_month == batch.reference_month,
                    PriceEntry.product_id == product.id,
                )
            )
            previous = current.base_price if current is not None else None
            result.changes.append(
                PriceChange(
                    sku=product.sku,
                    product_name=product.commercial_name,
                    previous_price=previous,
                    new_price=item.base_price,
                    change="NEW"
                    if previous is None
                    else "UNCHANGED"
                    if previous == item.base_price
                    else "CHANGED",
                )
            )
        return result
