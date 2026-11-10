"""Previa auditavel de atualizacao de catalogo e precos vinda do WhatsApp.

O arquivo ou a mensagem nunca altera o cadastro diretamente. A proposta guarda
os valores interpretados, compara cada campo com o CRM e so os materializa no
mesmo commit da confirmacao explicita do representante.
"""

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.pricing import (
    NO_PRICE_AVAILABILITIES,
    AvailabilityStatus,
    PriceEntry,
    PriceList,
    PriceListItem,
    PriceListSourceFile,
    PriceListStatus,
)
from crm_api.repositories.audit import AuditRepository


class PriceUpdateProposalNotFound(Exception):
    pass


class PriceUpdateProposalForbidden(Exception):
    pass


@dataclass(frozen=True)
class ProposedPriceRow:
    sku: str
    base_price: Decimal | None = None
    availability: AvailabilityStatus | None = None
    generated_sku: bool = False
    commercial_name: str | None = None
    family_name: str | None = None
    specification: str | None = None
    unit: str | None = None
    catalog_active: bool | None = None
    base_tax_rate: Decimal | None = None
    expected_arrival_date: date | None = None
    arrival_note: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ProposedPriceSourceFile:
    filename: str
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class FieldChange:
    field: str
    previous: str | None
    new: str | None


@dataclass(frozen=True)
class PriceChange:
    sku: str
    product_name: str
    previous_price: Decimal | None
    new_price: Decimal | None
    previous_availability: str | None
    new_availability: str
    change: str
    generated_sku: bool = False
    field_changes: list[FieldChange] = field(default_factory=list)
    new_family: bool = False


@dataclass
class PriceUpdateProposal:
    reference_month: date
    proposal_id: uuid.UUID | None = None
    duplicate_skus: list[str] = field(default_factory=list)
    # Mantido no contrato para compatibilidade; SKU ausente agora pode virar um
    # produto novo, desde que a linha tenha os dados minimos.
    unknown_skus: list[str] = field(default_factory=list)
    incomplete_rows: list[str] = field(default_factory=list)
    changes: list[PriceChange] = field(default_factory=list)

    @property
    def ready_for_confirmation(self) -> bool:
        return (
            self.proposal_id is not None
            and not self.duplicate_skus
            and not self.unknown_skus
            and not self.incomplete_rows
        )


@dataclass
class MaterializationResult:
    products_created: int = 0
    products_updated: int = 0
    families_created: int = 0


def _sku(value: str) -> str:
    return " ".join(value.strip().upper().split())[:120]


def _text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())[:limit]
    return normalized or None


def _name_key(value: str | None) -> str:
    plain = unicodedata.normalize("NFKD", value or "")
    plain = "".join(character for character in plain if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", plain).lower().split())


def _numbers(value: str | None) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+", _name_key(value)))


def _match_generated_product(
    row: ProposedPriceRow,
    products: list[tuple[Product, ProductFamily]],
) -> tuple[Product, ProductFamily] | None:
    """Resolve artigo sem SKU por nome + familia, sem confundir titulacoes proximas."""

    if not row.generated_sku or not row.commercial_name:
        return None
    wanted = _name_key(row.commercial_name)
    wanted_family = _name_key(row.family_name)
    exact = [pair for pair in products if _name_key(pair[0].commercial_name) == wanted]
    if wanted_family:
        exact_in_family = [pair for pair in exact if _name_key(pair[1].name) == wanted_family]
        if len(exact_in_family) == 1:
            return exact_in_family[0]
    if len(exact) == 1:
        return exact[0]
    wanted_numbers = _numbers(row.commercial_name)
    candidates: list[tuple[float, tuple[Product, ProductFamily]]] = []
    for pair in products:
        if _numbers(pair[0].commercial_name) != wanted_numbers:
            continue
        if wanted_family and _name_key(pair[1].name) != wanted_family:
            continue
        score = SequenceMatcher(None, wanted, _name_key(pair[0].commercial_name)).ratio()
        if score >= 0.84:
            candidates.append((score, pair))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return None
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.05:
        return None
    return candidates[0][1]


def _shown(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, AvailabilityStatus):
        return value.value
    if isinstance(value, bool):
        return "ativo" if value else "inativo"
    return str(value)


def _row_payload(row: ProposedPriceRow) -> dict:
    return {
        "sku": row.sku,
        "generated_sku": row.generated_sku,
        "commercial_name": row.commercial_name,
        "family_name": row.family_name,
        "specification": row.specification,
        "unit": row.unit,
        "catalog_active": row.catalog_active,
        "base_price": str(row.base_price) if row.base_price is not None else None,
        "base_tax_rate": str(row.base_tax_rate) if row.base_tax_rate is not None else None,
        "availability": row.availability.value if row.availability is not None else None,
        "expected_arrival_date": (
            row.expected_arrival_date.isoformat() if row.expected_arrival_date else None
        ),
        "arrival_note": row.arrival_note,
        "notes": row.notes,
    }


def _row_from_payload(payload: dict) -> ProposedPriceRow:
    return ProposedPriceRow(
        sku=payload["sku"],
        generated_sku=bool(payload.get("generated_sku", False)),
        commercial_name=payload.get("commercial_name"),
        family_name=payload.get("family_name"),
        specification=payload.get("specification"),
        unit=payload.get("unit"),
        catalog_active=payload.get("catalog_active"),
        base_price=(
            Decimal(payload["base_price"]) if payload.get("base_price") is not None else None
        ),
        base_tax_rate=(
            Decimal(payload["base_tax_rate"]) if payload.get("base_tax_rate") is not None else None
        ),
        availability=(
            AvailabilityStatus(payload["availability"]) if payload.get("availability") else None
        ),
        expected_arrival_date=(
            date.fromisoformat(payload["expected_arrival_date"])
            if payload.get("expected_arrival_date")
            else None
        ),
        arrival_note=payload.get("arrival_note"),
        notes=payload.get("notes"),
    )


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
        source_kind: str = "WHATSAPP_MESSAGE",
        source_file: ProposedPriceSourceFile | None = None,
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

        normalized = [self._normalize_row(row) for row in rows]
        counts: dict[str, int] = {}
        for row in normalized:
            counts[row.sku] = counts.get(row.sku, 0) + 1
        duplicates = sorted(sku for sku, count in counts.items() if count > 1)

        result = await self._review_rows(tenant_id, reference_month, normalized)
        result.duplicate_skus = duplicates
        if duplicates or result.incomplete_rows:
            return result

        digest = hashlib.sha256(source_wamid.encode("utf-8")).hexdigest()[:16]
        batch = PriceList(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=f"Atualizacao WhatsApp {digest}",
            reference_month=reference_month,
            valid_from=datetime(reference_month.year, reference_month.month, 1, tzinfo=UTC),
            currency="BRL",
            status=PriceListStatus.DRAFT,
            created_by=representative_user_id,
            source_wamid=source_wamid,
            source_kind=source_kind[:32],
            proposal_payload={"version": 1, "rows": [_row_payload(row) for row in normalized]},
        )
        self._session.add(batch)
        self._store_source_file(tenant_id, batch.id, source_file)
        await self._session.flush()
        result.proposal_id = batch.id
        return result

    async def get_owned(
        self, tenant_id: uuid.UUID, representative_user_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> PriceList:
        batch = await self._session.scalar(
            select(PriceList)
            .where(PriceList.id == proposal_id, PriceList.tenant_id == tenant_id)
            .with_for_update()
        )
        if batch is None:
            raise PriceUpdateProposalNotFound
        if batch.created_by != representative_user_id or batch.source_wamid is None:
            raise PriceUpdateProposalForbidden
        return batch

    async def materialize_for_confirmation(
        self,
        batch: PriceList,
        *,
        actor_user_id: uuid.UUID,
        request_id: str | None,
    ) -> MaterializationResult:
        """Aplica catalogo e monta os itens apenas dentro da confirmacao."""

        existing_items = list(
            await self._session.scalars(
                select(PriceListItem).where(PriceListItem.price_list_id == batch.id)
            )
        )
        if existing_items:
            return MaterializationResult()
        payload = batch.proposal_payload or {}
        rows = [_row_from_payload(item) for item in payload.get("rows", [])]
        if not rows:
            # Lotes antigos ja possuiam itens no momento da proposta. Um lote
            # sem payload e sem itens nao pode ser publicado vazio.
            raise ValueError("price update proposal has no staged rows")

        review = await self._review_rows(batch.tenant_id, batch.reference_month, rows)
        if review.incomplete_rows:
            raise ValueError("; ".join(review.incomplete_rows))

        audit = AuditRepository(self._session)
        result = MaterializationResult()
        product_rows = (
            await self._session.execute(
                select(Product, ProductFamily)
                .join(ProductFamily, ProductFamily.id == Product.family_id)
                .where(Product.tenant_id == batch.tenant_id)
            )
        ).all()
        products = {_sku(product.sku): (product, family) for product, family in product_rows}
        families = list(
            await self._session.scalars(
                select(ProductFamily).where(ProductFamily.tenant_id == batch.tenant_id)
            )
        )
        families_by_name = {family.name.casefold(): family for family in families}
        next_family_order = max((family.display_order for family in families), default=0) + 10
        staged_items: dict[uuid.UUID, PriceListItem] = {}
        staged_explicit_values: dict[uuid.UUID, dict[str, object]] = {}

        for order, row in enumerate(rows):
            current_pair = products.get(row.sku) or _match_generated_product(row, product_rows)
            if current_pair is not None and current_pair[0].id in staged_items:
                # O mesmo produto pode aparecer duas vezes na leitura (por
                # exemplo, uma vez pelo SKU e outra pelo nome aproximado). A
                # primeira linha preserva os dados cadastrais; a segunda pode
                # apenas complementar os campos comerciais sem divergir deles.
                product = current_pair[0]
                staged_item = staged_items[product.id]
                explicit_values = {
                    field: value
                    for field, value in {
                        "base_price": row.base_price,
                        "base_tax_rate": row.base_tax_rate,
                        "availability": row.availability,
                        "expected_arrival_date": row.expected_arrival_date,
                        "arrival_note": row.arrival_note,
                        "notes": row.notes,
                    }.items()
                    if value is not None
                }
                previous_explicit = staged_explicit_values[product.id]
                conflicting = sorted(
                    field
                    for field, value in explicit_values.items()
                    if field in previous_explicit and previous_explicit[field] != value
                )
                if conflicting:
                    raise ValueError(
                        f"{product.sku}: linhas do arquivo correspondem ao mesmo produto "
                        f"com dados diferentes em {', '.join(conflicting)}"
                    )
                previous_explicit.update(explicit_values)
                if row.base_price is not None:
                    staged_item.base_price = row.base_price
                if row.availability is not None:
                    staged_item.availability = row.availability
                if row.expected_arrival_date is not None:
                    staged_item.expected_arrival_date = row.expected_arrival_date
                if row.arrival_note is not None:
                    staged_item.arrival_note = row.arrival_note
                if row.base_tax_rate is not None:
                    staged_item.item_tax_rate = row.base_tax_rate
                if row.notes is not None:
                    staged_item.notes = row.notes
                continue
            family = None
            if row.family_name:
                family = families_by_name.get(row.family_name.casefold())
                if family is None:
                    family = ProductFamily(
                        id=uuid.uuid4(),
                        tenant_id=batch.tenant_id,
                        name=row.family_name,
                        display_order=next_family_order,
                        active=True,
                    )
                    next_family_order += 10
                    result.families_created += 1
                    self._session.add(family)
                    # `Product.family_id` recebe o UUID diretamente, sem uma
                    # relationship ORM que informe a ordem de dependência ao
                    # SQLAlchemy. Persiste a família antes de qualquer query
                    # disparar autoflush dos produtos novos.
                    await self._session.flush()
                    families_by_name[family.name.casefold()] = family
                    audit.record(
                        action="PRODUCT_FAMILY_CREATED_FROM_WHATSAPP",
                        entity="product_families",
                        tenant_id=batch.tenant_id,
                        actor_user_id=actor_user_id,
                        entity_id=family.id,
                        after={"name": family.name},
                        request_id=request_id,
                    )

            if current_pair is None:
                product = Product(
                    id=uuid.uuid4(),
                    tenant_id=batch.tenant_id,
                    family_id=family.id,
                    sku=row.sku,
                    commercial_name=row.commercial_name,
                    specification=row.specification,
                    unit=row.unit or "KG",
                    active=row.catalog_active if row.catalog_active is not None else True,
                )
                self._session.add(product)
                result.products_created += 1
                products[row.sku] = (product, family)
                audit.record(
                    action="PRODUCT_CREATED_FROM_WHATSAPP",
                    entity="products",
                    tenant_id=batch.tenant_id,
                    actor_user_id=actor_user_id,
                    entity_id=product.id,
                    after={
                        "sku": product.sku,
                        "commercial_name": product.commercial_name,
                        "family": family.name,
                        "unit": product.unit,
                    },
                    request_id=request_id,
                )
            else:
                product, current_family = current_pair
                before = {
                    "commercial_name": product.commercial_name,
                    "family": current_family.name,
                    "specification": product.specification,
                    "unit": product.unit,
                    "active": product.active,
                }
                if row.commercial_name is not None:
                    product.commercial_name = row.commercial_name
                if family is not None:
                    product.family_id = family.id
                if row.specification is not None:
                    product.specification = row.specification
                if row.unit is not None:
                    product.unit = row.unit
                if row.catalog_active is not None:
                    product.active = row.catalog_active
                after = {
                    "commercial_name": product.commercial_name,
                    "family": family.name if family is not None else current_family.name,
                    "specification": product.specification,
                    "unit": product.unit,
                    "active": product.active,
                }
                if before != after:
                    result.products_updated += 1
                    audit.record(
                        action="PRODUCT_UPDATED_FROM_WHATSAPP",
                        entity="products",
                        tenant_id=batch.tenant_id,
                        actor_user_id=actor_user_id,
                        entity_id=product.id,
                        before=before,
                        after=after,
                        request_id=request_id,
                    )

            explicit_values = {
                field: value
                for field, value in {
                    "base_price": row.base_price,
                    "base_tax_rate": row.base_tax_rate,
                    "availability": row.availability,
                    "expected_arrival_date": row.expected_arrival_date,
                    "arrival_note": row.arrival_note,
                    "notes": row.notes,
                }.items()
                if value is not None
            }
            previous_explicit = staged_explicit_values.get(product.id)
            if previous_explicit is not None:
                conflicting = sorted(
                    field
                    for field, value in explicit_values.items()
                    if field in previous_explicit and previous_explicit[field] != value
                )
                if conflicting:
                    raise ValueError(
                        f"{product.sku}: linhas do arquivo correspondem ao mesmo produto "
                        f"com dados diferentes em {', '.join(conflicting)}"
                    )
                previous_explicit.update(explicit_values)
            else:
                staged_explicit_values[product.id] = explicit_values

            current = await self._current_price(batch.tenant_id, batch.reference_month, product.id)
            if current is None and current_pair is not None and not self._has_price_fields(row):
                # Uma alteracao apenas cadastral nao deve criar artificialmente
                # um preco zero para um artigo que ainda nao tem competencia.
                continue
            availability = row.availability or (
                current.availability if current is not None else AvailabilityStatus.AVAILABLE
            )
            price = row.base_price
            if price is None:
                price = current.base_price if current is not None else Decimal("0")
            staged_item = staged_items.get(product.id)
            if staged_item is not None:
                # Duas leituras equivalentes do mesmo artigo formam uma única
                # linha do lote. Campos explícitos complementares prevalecem;
                # divergências já foram recusadas acima.
                if row.base_price is not None:
                    staged_item.base_price = row.base_price
                if row.availability is not None:
                    staged_item.availability = row.availability
                if row.expected_arrival_date is not None:
                    staged_item.expected_arrival_date = row.expected_arrival_date
                if row.arrival_note is not None:
                    staged_item.arrival_note = row.arrival_note
                if row.base_tax_rate is not None:
                    staged_item.item_tax_rate = row.base_tax_rate
                if row.notes is not None:
                    staged_item.notes = row.notes
                continue
            staged_item = PriceListItem(
                    id=uuid.uuid4(),
                    tenant_id=batch.tenant_id,
                    price_list_id=batch.id,
                    product_id=product.id,
                    base_price=price,
                    availability=availability,
                    expected_arrival_date=(
                        row.expected_arrival_date
                        if row.expected_arrival_date is not None
                        else current.expected_arrival_date
                        if current
                        else None
                    ),
                    available_quantity_kg=current.available_quantity_kg if current else None,
                    arrival_note=(
                        row.arrival_note
                        if row.arrival_note is not None
                        else current.arrival_note
                        if current
                        else None
                    ),
                    item_tax_rate=(
                        row.base_tax_rate
                        if row.base_tax_rate is not None
                        else current.base_tax_rate
                        if current
                        else None
                    ),
                    notes=(
                        row.notes if row.notes is not None else current.notes if current else None
                    ),
                    display_order=current.display_order if current else order,
                )
            self._session.add(staged_item)
            staged_items[product.id] = staged_item
        await self._session.flush()
        return result

    def _normalize_row(self, row: ProposedPriceRow) -> ProposedPriceRow:
        unit = _text(row.unit, 30)
        return ProposedPriceRow(
            sku=_sku(row.sku),
            generated_sku=row.generated_sku,
            commercial_name=_text(row.commercial_name, 300),
            family_name=_text(row.family_name, 200),
            specification=_text(row.specification, 500),
            unit=unit.upper() if unit else None,
            catalog_active=row.catalog_active,
            base_price=row.base_price,
            base_tax_rate=row.base_tax_rate,
            availability=row.availability,
            expected_arrival_date=row.expected_arrival_date,
            arrival_note=_text(row.arrival_note, 500),
            notes=_text(row.notes, 1000),
        )

    async def _review_rows(
        self, tenant_id: uuid.UUID, reference_month: date, rows: list[ProposedPriceRow]
    ) -> PriceUpdateProposal:
        result = PriceUpdateProposal(reference_month=reference_month)
        product_rows = (
            await self._session.execute(
                select(Product, ProductFamily)
                .join(ProductFamily, ProductFamily.id == Product.family_id)
                .where(Product.tenant_id == tenant_id)
            )
        ).all()
        by_sku = {_sku(product.sku): (product, family) for product, family in product_rows}
        family_names = {
            name.casefold()
            for name in await self._session.scalars(
                select(ProductFamily.name).where(ProductFamily.tenant_id == tenant_id)
            )
        }

        for row in rows:
            pair = by_sku.get(row.sku) or _match_generated_product(row, product_rows)
            if pair is None:
                missing = []
                if not row.commercial_name:
                    missing.append("nome comercial")
                if not row.family_name:
                    missing.append("familia")
                availability = row.availability or AvailabilityStatus.AVAILABLE
                if row.base_price is None and availability not in NO_PRICE_AVAILABILITIES:
                    missing.append("preco-base")
                if missing:
                    result.incomplete_rows.append(
                        f"{row.sku}: produto novo sem {', '.join(missing)}"
                    )
                changes = self._new_product_changes(row, availability)
                result.changes.append(
                    PriceChange(
                        sku=row.sku,
                        product_name=row.commercial_name or "Produto novo",
                        previous_price=None,
                        new_price=row.base_price,
                        previous_availability=None,
                        new_availability=availability.value,
                        change="NEW",
                        generated_sku=row.generated_sku,
                        field_changes=changes,
                        new_family=bool(
                            row.family_name and row.family_name.casefold() not in family_names
                        ),
                    )
                )
                continue

            product, family = pair
            current = await self._current_price(tenant_id, reference_month, product.id)
            availability = row.availability or (
                current.availability if current is not None else AvailabilityStatus.AVAILABLE
            )
            price = (
                row.base_price
                if row.base_price is not None
                else (current.base_price if current is not None else None)
            )
            if (
                price is None
                and availability not in NO_PRICE_AVAILABILITIES
                and self._has_price_fields(row)
            ):
                result.incomplete_rows.append(
                    f"{row.sku}: nao ha preco vigente; informe o preco-base"
                )
            if not self._has_explicit_change(row):
                result.incomplete_rows.append(f"{row.sku}: nenhum dado para comparar")

            changes: list[FieldChange] = []
            self._compare(changes, "nome comercial", product.commercial_name, row.commercial_name)
            self._compare(changes, "familia", family.name, row.family_name)
            self._compare(changes, "especificacao", product.specification, row.specification)
            self._compare(changes, "unidade", product.unit, row.unit)
            self._compare(changes, "situacao cadastral", product.active, row.catalog_active)
            self._compare(
                changes, "preco-base", current.base_price if current else None, row.base_price
            )
            self._compare(
                changes,
                "ICMS embutido",
                current.base_tax_rate if current else None,
                row.base_tax_rate,
            )
            self._compare(
                changes,
                "disponibilidade",
                current.availability if current else None,
                row.availability,
            )
            self._compare(
                changes,
                "previsao de chegada",
                current.expected_arrival_date if current else None,
                row.expected_arrival_date,
            )
            self._compare(
                changes,
                "observacao de chegada",
                current.arrival_note if current else None,
                row.arrival_note,
            )
            self._compare(changes, "observacoes", current.notes if current else None, row.notes)
            result.changes.append(
                PriceChange(
                    sku=product.sku,
                    product_name=row.commercial_name or product.commercial_name,
                    previous_price=current.base_price if current else None,
                    new_price=price,
                    previous_availability=current.availability.value if current else None,
                    new_availability=availability.value,
                    change="CHANGED" if changes else "UNCHANGED",
                    generated_sku=False,
                    field_changes=changes,
                    new_family=bool(
                        row.family_name and row.family_name.casefold() not in family_names
                    ),
                )
            )
        return result

    @staticmethod
    def _compare(changes: list[FieldChange], field_name: str, previous, proposed) -> None:
        if proposed is not None and proposed != previous:
            changes.append(FieldChange(field_name, _shown(previous), _shown(proposed)))

    @staticmethod
    def _has_explicit_change(row: ProposedPriceRow) -> bool:
        return any(
            value is not None
            for value in (
                row.commercial_name,
                row.family_name,
                row.specification,
                row.unit,
                row.catalog_active,
                row.base_price,
                row.base_tax_rate,
                row.availability,
                row.expected_arrival_date,
                row.arrival_note,
                row.notes,
            )
        )

    @staticmethod
    def _has_price_fields(row: ProposedPriceRow) -> bool:
        return any(
            value is not None
            for value in (
                row.base_price,
                row.base_tax_rate,
                row.availability,
                row.expected_arrival_date,
                row.arrival_note,
                row.notes,
            )
        )

    @staticmethod
    def _new_product_changes(
        row: ProposedPriceRow, availability: AvailabilityStatus
    ) -> list[FieldChange]:
        values = (
            ("nome comercial", row.commercial_name),
            ("familia", row.family_name),
            ("especificacao", row.specification),
            ("unidade", row.unit or "KG"),
            ("situacao cadastral", row.catalog_active if row.catalog_active is not None else True),
            ("preco-base", row.base_price),
            ("ICMS embutido", row.base_tax_rate),
            ("disponibilidade", availability),
            ("previsao de chegada", row.expected_arrival_date),
            ("observacao de chegada", row.arrival_note),
            ("observacoes", row.notes),
        )
        return [
            FieldChange(name, None, _shown(value)) for name, value in values if value is not None
        ]

    async def _current_price(
        self, tenant_id: uuid.UUID, reference_month: date, product_id: uuid.UUID
    ) -> PriceEntry | None:
        return await self._session.scalar(
            select(PriceEntry).where(
                PriceEntry.tenant_id == tenant_id,
                PriceEntry.reference_month == reference_month,
                PriceEntry.product_id == product_id,
            )
        )

    def _store_source_file(
        self,
        tenant_id: uuid.UUID,
        price_list_id: uuid.UUID,
        source_file: ProposedPriceSourceFile | None,
    ) -> None:
        if source_file is None:
            return
        allowed_mime_types = {
            "application/pdf",
            "text/csv",
            "text/plain",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        mime_type = source_file.mime_type.strip().lower()
        filename = source_file.filename.strip()[:255]
        if not filename or mime_type not in allowed_mime_types:
            raise ValueError("unsupported price source file")
        if not source_file.content or len(source_file.content) > 15 * 1024 * 1024:
            raise ValueError("invalid price source file size")
        self._session.add(
            PriceListSourceFile(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                price_list_id=price_list_id,
                filename=filename,
                mime_type=mime_type,
                byte_size=len(source_file.content),
                sha256=hashlib.sha256(source_file.content).hexdigest(),
                content=source_file.content,
            )
        )

    async def _describe(self, batch: PriceList) -> PriceUpdateProposal:
        payload = batch.proposal_payload or {}
        if payload.get("rows"):
            result = await self._review_rows(
                batch.tenant_id,
                batch.reference_month,
                [_row_from_payload(item) for item in payload["rows"]],
            )
            result.proposal_id = batch.id
            return result

        # Compatibilidade com propostas criadas antes da previa em JSON.
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
            current = await self._current_price(batch.tenant_id, batch.reference_month, product.id)
            changes: list[FieldChange] = []
            self._compare(
                changes, "preco-base", current.base_price if current else None, item.base_price
            )
            self._compare(
                changes,
                "disponibilidade",
                current.availability if current else None,
                item.availability,
            )
            result.changes.append(
                PriceChange(
                    sku=product.sku,
                    product_name=product.commercial_name,
                    previous_price=current.base_price if current else None,
                    new_price=item.base_price,
                    previous_availability=current.availability.value if current else None,
                    new_availability=item.availability.value,
                    change="CHANGED" if changes else "UNCHANGED",
                    field_changes=changes,
                )
            )
        return result
