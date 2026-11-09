from datetime import date
from decimal import Decimal

import pytest
from conftest import build_portal_world
from sqlalchemy import select

from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceEntry,
    PriceList,
    PriceListSourceFile,
    PriceListStatus,
)
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.price_entries import PriceEntryRepository
from crm_api.services.price_publication import PricePublicationService
from crm_api.services.price_update import (
    ProposedPriceRow,
    ProposedPriceSourceFile,
    RepresentativePriceUpdateService,
)


@pytest.mark.asyncio
async def test_proposta_guarda_pdf_original_vinculado_ao_lote_e_autor():
    world = await build_portal_world()
    content = b"%PDF-1.4 tabela de teste"
    try:
        async with world.app.state.session_factory() as session:
            proposal = await RepresentativePriceUpdateService(session).propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.with-file",
                reference_month=date(2026, 11, 1),
                source_kind="WHATSAPP_PDF",
                source_file=ProposedPriceSourceFile(
                    filename="tabela especial.pdf",
                    mime_type="application/pdf",
                    content=content,
                ),
                rows=[ProposedPriceRow("TEX-75-36-CRU", Decimal("12.50"))],
            )
            await session.commit()
            batch = await session.get(PriceList, proposal.proposal_id)
            attachment = await session.scalar(
                select(PriceListSourceFile).where(
                    PriceListSourceFile.price_list_id == proposal.proposal_id
                )
            )

            assert batch.created_by == world.representative_a_id
            assert batch.source_kind == "WHATSAPP_PDF"
            assert attachment.filename == "tabela especial.pdf"
            assert attachment.content == content
            assert attachment.byte_size == len(content)
            assert len(attachment.sha256) == 64
    finally:
        await world.app.state.engine.dispose()


@pytest.mark.asyncio
async def test_proposta_valida_duplicidade_compara_e_so_publica_apos_confirmacao():
    world = await build_portal_world()
    reference_month = date(2026, 11, 1)
    try:
        async with world.app.state.session_factory() as session:
            session.add(
                PriceEntry(
                    tenant_id=world.tenant_id,
                    reference_month=reference_month,
                    product_id=world.product_id,
                    base_price=Decimal("10.0000"),
                    availability=AvailabilityStatus.AVAILABLE,
                )
            )
            await session.commit()

        async with world.app.state.session_factory() as session:
            service = RepresentativePriceUpdateService(session)
            duplicate = await service.propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.duplicate",
                reference_month=reference_month,
                rows=[
                    ProposedPriceRow("TEX-75-36-CRU", Decimal("11.00")),
                    ProposedPriceRow("tex-75-36-cru", Decimal("12.00")),
                ],
            )
            assert duplicate.duplicate_skus == ["TEX-75-36-CRU"]
            assert duplicate.proposal_id is None

            proposal = await service.propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.valid",
                reference_month=reference_month,
                rows=[ProposedPriceRow("tex-75-36-cru", Decimal("12.5000"))],
            )
            await session.commit()
            assert proposal.ready_for_confirmation is True
            assert proposal.changes[0].previous_price == Decimal("10.0000")
            assert proposal.changes[0].new_price == Decimal("12.5000")
            batch = await session.get(PriceList, proposal.proposal_id)
            assert batch.status is PriceListStatus.DRAFT

        async with world.app.state.session_factory() as session:
            result = await PricePublicationService(
                session=session,
                entries=PriceEntryRepository(session),
                audit=AuditRepository(session),
            ).publish_batch(
                tenant_id=world.tenant_id,
                batch_id=proposal.proposal_id,
                actor_user_id=world.representative_a_id,
                request_id="wamid.confirm",
            )
            await session.commit()
            assert result.atualizados == 1
            current = await session.scalar(
                select(PriceEntry).where(
                    PriceEntry.tenant_id == world.tenant_id,
                    PriceEntry.reference_month == reference_month,
                    PriceEntry.product_id == world.product_id,
                )
            )
            assert current.base_price == Decimal("12.5000")
    finally:
        await world.app.state.engine.dispose()


@pytest.mark.asyncio
async def test_proposta_rejeita_sku_desconhecido_sem_criar_rascunho():
    world = await build_portal_world()
    try:
        async with world.app.state.session_factory() as session:
            proposal = await RepresentativePriceUpdateService(session).propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.unknown",
                reference_month=date(2026, 11, 1),
                rows=[ProposedPriceRow("NAO-EXISTE", Decimal("12.50"))],
            )
            assert proposal.unknown_skus == ["NAO-EXISTE"]
            assert proposal.proposal_id is None
    finally:
        await world.app.state.engine.dispose()


@pytest.mark.asyncio
async def test_proposta_suspende_produto_sem_apagar_preco_anterior():
    world = await build_portal_world()
    reference_month = date(2026, 11, 1)
    try:
        async with world.app.state.session_factory() as session:
            session.add(
                PriceEntry(
                    tenant_id=world.tenant_id,
                    reference_month=reference_month,
                    product_id=world.product_id,
                    base_price=Decimal("10.0000"),
                    availability=AvailabilityStatus.AVAILABLE,
                )
            )
            await session.commit()

        async with world.app.state.session_factory() as session:
            proposal = await RepresentativePriceUpdateService(session).propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.suspended",
                reference_month=reference_month,
                rows=[
                    ProposedPriceRow(
                        "TEX-75-36-CRU",
                        availability=AvailabilityStatus.SUSPENDED,
                    )
                ],
            )
            await session.commit()
            assert proposal.changes[0].previous_price == Decimal("10.0000")
            assert proposal.changes[0].new_price == Decimal("10.0000")
            assert proposal.changes[0].new_availability == "SUSPENDED"

            batch = await session.get(PriceList, proposal.proposal_id)
            await PricePublicationService(
                session=session,
                entries=PriceEntryRepository(session),
                audit=AuditRepository(session),
            ).publish_batch(
                tenant_id=world.tenant_id,
                batch_id=batch.id,
                actor_user_id=world.representative_a_id,
                request_id="wamid.suspended.confirm",
            )
            await session.commit()
            current = await session.scalar(
                select(PriceEntry).where(
                    PriceEntry.tenant_id == world.tenant_id,
                    PriceEntry.reference_month == reference_month,
                    PriceEntry.product_id == world.product_id,
                )
            )
            assert current.availability is AvailabilityStatus.SUSPENDED
            assert current.base_price == Decimal("10.0000")
    finally:
        await world.app.state.engine.dispose()
