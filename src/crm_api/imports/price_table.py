import argparse
import asyncio
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.core.config import get_settings
from crm_api.core.database import create_session_factory
from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.customer import Tenant
from crm_api.models.pricing import AvailabilityStatus, PriceList, PriceListItem, PriceListStatus

_AVAILABILITIES = {"AVAILABLE", "OUT_OF_STOCK", "SUSPENDED", "FUTURE_ARRIVAL", "CONSULT"}
_NO_PRICE_AVAILABILITIES = {"OUT_OF_STOCK", "SUSPENDED", "CONSULT"}


def _decimal(value: str, *, field: str) -> Decimal:
    try:
        normalized = value.strip()
        if "," in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        return Decimal(normalized)
    except (AttributeError, InvalidOperation) as error:
        raise ValueError(f"{field} must be a decimal") from error


def _integer(value: str, *, field: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an integer") from error


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value.strip() else None


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file, delimiter=";"))
    expected_columns = {
        "family_name",
        "family_order",
        "sku",
        "commercial_name",
        "specification",
        "availability",
        "base_price",
        "expected_arrival_date",
        "arrival_note",
        "display_order",
        "notes",
    }
    if not rows or set(rows[0]) != expected_columns:
        raise ValueError("CSV columns do not match the documented price-table template")
    return rows


async def _get_tenant(session: AsyncSession, slug: str) -> Tenant:
    tenant = await session.scalar(
        select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True))
    )
    if tenant is None:
        raise ValueError(f"active tenant not found: {slug}")
    return tenant


async def _get_or_create_family(
    session: AsyncSession, tenant_id: UUID, row: dict[str, str]
) -> ProductFamily:
    family = await session.scalar(
        select(ProductFamily).where(
            ProductFamily.tenant_id == tenant_id,
            ProductFamily.name == row["family_name"].strip(),
        )
    )
    if family is not None:
        return family
    family = ProductFamily(
        tenant_id=tenant_id,
        name=row["family_name"].strip(),
        display_order=_integer(row["family_order"], field="family_order"),
    )
    session.add(family)
    await session.flush()
    return family


async def _get_or_create_product(
    session: AsyncSession, tenant_id: UUID, family: ProductFamily, row: dict[str, str]
) -> Product:
    product = await session.scalar(
        select(Product).where(Product.tenant_id == tenant_id, Product.sku == row["sku"].strip())
    )
    if product is not None:
        if (
            product.family_id != family.id
            or product.commercial_name != row["commercial_name"].strip()
        ):
            raise ValueError(f"existing product conflicts with CSV: {product.sku}")
        return product
    product = Product(
        tenant_id=tenant_id,
        family_id=family.id,
        sku=row["sku"].strip(),
        commercial_name=row["commercial_name"].strip(),
        specification=row["specification"].strip() or None,
    )
    session.add(product)
    await session.flush()
    return product


async def import_price_table(
    session: AsyncSession,
    *,
    tenant_slug: str,
    source_path: Path,
    name: str,
    reference_month: date,
    valid_from: datetime,
    valid_until: datetime | None,
) -> PriceList:
    if reference_month.day != 1:
        raise ValueError("reference_month must be the first day of the month")
    if valid_until is not None and valid_until <= valid_from:
        raise ValueError("valid_until must be later than valid_from")

    rows = _load_rows(source_path)
    tenant = await _get_tenant(session, tenant_slug)
    existing = await session.scalar(
        select(PriceList).where(
            PriceList.tenant_id == tenant.id,
            PriceList.name == name,
            PriceList.reference_month == reference_month,
        )
    )
    if existing is not None:
        raise ValueError("a price list with this name and reference month already exists")

    price_list = PriceList(
        tenant_id=tenant.id,
        name=name,
        reference_month=reference_month,
        valid_from=valid_from,
        valid_until=valid_until,
        status=PriceListStatus.DRAFT,
    )
    session.add(price_list)
    await session.flush()

    seen_skus: set[str] = set()
    for row in rows:
        sku = row["sku"].strip()
        availability = row["availability"].strip()
        if not sku or sku in seen_skus:
            raise ValueError(f"sku must be present and unique: {sku or '<empty>'}")
        if availability not in _AVAILABILITIES:
            raise ValueError(f"invalid availability for {sku}: {availability}")
        if not row["commercial_name"].strip() or not row["family_name"].strip():
            raise ValueError(f"family_name and commercial_name are required for {sku}")
        if not row["base_price"].strip() and availability not in _NO_PRICE_AVAILABILITIES:
            raise ValueError(
                f"base_price is required for {sku} when availability is {availability}"
            )

        family = await _get_or_create_family(session, tenant.id, row)
        product = await _get_or_create_product(session, tenant.id, family, row)
        session.add(
            PriceListItem(
                tenant_id=tenant.id,
                price_list_id=price_list.id,
                product_id=product.id,
                base_price=(
                    _decimal(row["base_price"], field=f"base_price for {sku}")
                    if row["base_price"].strip()
                    else Decimal("0")
                ),
                availability=AvailabilityStatus(availability),
                expected_arrival_date=_optional_date(row["expected_arrival_date"]),
                arrival_note=row["arrival_note"].strip() or None,
                notes=row["notes"].strip() or None,
                display_order=_integer(row["display_order"], field=f"display_order for {sku}"),
            )
        )
        seen_skus.add(sku)
    return price_list


async def activate_price_list(
    session: AsyncSession, *, tenant_slug: str, price_list_id: UUID
) -> PriceList:
    tenant = await _get_tenant(session, tenant_slug)
    price_list = await session.scalar(
        select(PriceList).where(PriceList.id == price_list_id, PriceList.tenant_id == tenant.id)
    )
    if price_list is None:
        raise ValueError("price list not found for tenant")
    if price_list.status is not PriceListStatus.DRAFT:
        raise ValueError("only a DRAFT price list can be activated")

    candidate_until = price_list.valid_until or datetime.max.replace(
        tzinfo=price_list.valid_from.tzinfo
    )
    overlapping_active = await session.scalar(
        select(PriceList.id).where(
            PriceList.tenant_id == tenant.id,
            PriceList.status == PriceListStatus.ACTIVE,
            PriceList.id != price_list.id,
            PriceList.valid_from < candidate_until,
            (PriceList.valid_until.is_(None) | (PriceList.valid_until > price_list.valid_from)),
        )
    )
    if overlapping_active is not None:
        raise ValueError("an overlapping ACTIVE price list already exists")
    price_list.status = PriceListStatus.ACTIVE
    await session.flush()
    return price_list


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a reviewed CRM price table from CSV")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--reference-month", type=date.fromisoformat)
    parser.add_argument("--valid-from", type=datetime.fromisoformat)
    parser.add_argument("--valid-until", type=datetime.fromisoformat)
    parser.add_argument("--activate-price-list", type=UUID)
    return parser.parse_args()


async def _main() -> None:
    args = _arguments()
    settings = get_settings()
    engine, session_factory = create_session_factory(settings)
    try:
        async with session_factory() as session:
            async with session.begin():
                if args.activate_price_list is not None:
                    import_arguments = (
                        args.file,
                        args.name,
                        args.reference_month,
                        args.valid_from,
                        args.valid_until,
                    )
                    if any(import_arguments):
                        raise ValueError("activation does not accept import arguments")
                    price_list = await activate_price_list(
                        session,
                        tenant_slug=settings.tenant_slug,
                        price_list_id=args.activate_price_list,
                    )
                    action = "Activated"
                else:
                    if not all((args.file, args.name, args.reference_month, args.valid_from)):
                        raise ValueError("file, name, reference_month and valid_from are required")
                    if not args.file.is_file():
                        raise ValueError(f"CSV file not found: {args.file}")
                    price_list = await import_price_table(
                        session,
                        tenant_slug=settings.tenant_slug,
                        source_path=args.file,
                        name=args.name,
                        reference_month=args.reference_month,
                        valid_from=args.valid_from,
                        valid_until=args.valid_until,
                    )
                    action = "Imported"
        print(f"{action} {price_list.id} as {price_list.status.value}.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
