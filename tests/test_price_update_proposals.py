from datetime import date
from decimal import Decimal

import pytest
from conftest import build_portal_world
from sqlalchemy import select, text

from crm_api.models.catalog import Product, ProductFamily
from crm_api.models.pricing import (
    AvailabilityStatus,
    PriceEntry,
    PriceList,
    PriceListItem,
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
async def test_proposta_pendente_e_anexo_isolado_sobrevivem_fora_do_gateway():
    world = await build_portal_world()
    try:
        async with world.app.state.session_factory() as session:
            service = RepresentativePriceUpdateService(session)
            attached, created = await service.attach_source_file(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.attachment-only",
                reference_month=date(2026, 11, 1),
                source_kind="WHATSAPP_PDF",
                source_file=ProposedPriceSourceFile(
                    filename="consulta.pdf",
                    mime_type="application/pdf",
                    content=b"%PDF arquivo",
                ),
            )
            proposal = await service.propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.persisted-proposal",
                reference_month=date(2026, 11, 1),
                rows=[ProposedPriceRow("TEX-75-36-CRU", Decimal("15.00"))],
            )
            await session.commit()

            assert created is True
            assert attached.proposal_payload["attachment_only"] is True
            pending = await service.latest_pending_owned(
                world.tenant_id, world.representative_a_id
            )
            assert pending.id == proposal.proposal_id

            await service.cancel_owned(
                world.tenant_id, world.representative_a_id, proposal.proposal_id
            )
            await session.commit()
            assert (
                await service.latest_pending_owned(
                    world.tenant_id, world.representative_a_id
                )
                is None
            )
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
            service = RepresentativePriceUpdateService(session)
            batch = await service.get_owned(
                world.tenant_id, world.representative_a_id, proposal.proposal_id
            )
            await service.materialize_for_confirmation(
                batch,
                actor_user_id=world.representative_a_id,
                request_id="wamid.confirm",
            )
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
async def test_proposta_pede_dados_minimos_para_produto_novo_sem_criar_rascunho():
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
            assert proposal.incomplete_rows == [
                "NAO-EXISTE: produto novo sem nome comercial, familia"
            ]
            assert proposal.changes[0].change == "NEW"
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
            service = RepresentativePriceUpdateService(session)
            await service.materialize_for_confirmation(
                batch,
                actor_user_id=world.representative_a_id,
                request_id="wamid.suspended.confirm",
            )
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


@pytest.mark.asyncio
async def test_produto_novo_so_aparece_no_catalogo_depois_da_confirmacao():
    world = await build_portal_world()
    reference_month = date(2026, 11, 1)
    try:
        async with world.app.state.session_factory() as session:
            service = RepresentativePriceUpdateService(session)
            proposal = await service.propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.new-product",
                reference_month=reference_month,
                rows=[
                    ProposedPriceRow(
                        sku="PEU-20",
                        commercial_name="20/1 PUE",
                        family_name="Elastano",
                        unit="kg",
                        base_price=Decimal("13.20"),
                        availability=AvailabilityStatus.AVAILABLE,
                    )
                ],
            )
            await session.commit()
            assert proposal.ready_for_confirmation is True
            assert proposal.changes[0].change == "NEW"
            assert (
                await session.scalar(
                    select(Product).where(
                        Product.tenant_id == world.tenant_id, Product.sku == "PEU-20"
                    )
                )
                is None
            )

        async with world.app.state.session_factory() as session:
            # Produção usa PostgreSQL com FKs ativas. Esta guarda faz o SQLite
            # reproduzir a ordem de inserção exigida ao criar família + produto.
            await session.execute(text("PRAGMA foreign_keys=ON"))
            service = RepresentativePriceUpdateService(session)
            batch = await service.get_owned(
                world.tenant_id, world.representative_a_id, proposal.proposal_id
            )
            await service.materialize_for_confirmation(
                batch,
                actor_user_id=world.representative_a_id,
                request_id="wamid.new-product.confirm",
            )
            result = await PricePublicationService(
                session=session,
                entries=PriceEntryRepository(session),
                audit=AuditRepository(session),
            ).publish_batch(
                tenant_id=world.tenant_id,
                batch_id=batch.id,
                actor_user_id=world.representative_a_id,
                request_id="wamid.new-product.confirm",
            )
            await session.commit()
            product = await session.scalar(
                select(Product).where(Product.tenant_id == world.tenant_id, Product.sku == "PEU-20")
            )
            assert product is not None
            assert product.unit == "KG"
            assert result.criados == 1
    finally:
        await world.app.state.engine.dispose()


@pytest.mark.asyncio
async def test_alteracao_cadastral_e_comparada_e_so_aplicada_apos_confirmar():
    world = await build_portal_world()
    try:
        async with world.app.state.session_factory() as session:
            product = await session.get(Product, world.product_id)
            original_name = product.commercial_name
            proposal = await RepresentativePriceUpdateService(session).propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.catalog-change",
                reference_month=date(2026, 11, 1),
                rows=[
                    ProposedPriceRow(
                        sku=product.sku,
                        commercial_name="75/36 trama revisado",
                        unit="cone",
                    )
                ],
            )
            await session.commit()
            assert proposal.changes[0].change == "CHANGED"
            assert {change.field for change in proposal.changes[0].field_changes} == {
                "nome comercial",
                "unidade",
            }
            product = await session.get(Product, world.product_id)
            assert product.commercial_name == original_name

        async with world.app.state.session_factory() as session:
            service = RepresentativePriceUpdateService(session)
            batch = await service.get_owned(
                world.tenant_id, world.representative_a_id, proposal.proposal_id
            )
            materialized = await service.materialize_for_confirmation(
                batch,
                actor_user_id=world.representative_a_id,
                request_id="wamid.catalog-change.confirm",
            )
            await session.commit()
            product = await session.get(Product, world.product_id)
            assert product.commercial_name == "75/36 trama revisado"
            assert product.unit == "CONE"
            assert materialized.products_updated == 1
    finally:
        await world.app.state.engine.dispose()


@pytest.mark.asyncio
async def test_linha_sem_sku_de_origem_encontra_produto_existente_pelo_nome():
    world = await build_portal_world()
    try:
        async with world.app.state.session_factory() as session:
            product = await session.get(Product, world.product_id)
            proposal = await RepresentativePriceUpdateService(session).propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.generated-name-match",
                reference_month=date(2026, 11, 1),
                rows=[
                    ProposedPriceRow(
                        sku="AUTO-1234567890",
                        generated_sku=True,
                        commercial_name=product.commercial_name,
                        family_name="Texturizado cru",
                        base_price=Decimal("14.38"),
                    )
                ],
            )
            assert proposal.ready_for_confirmation is True
            assert proposal.changes[0].sku == product.sku
            assert proposal.changes[0].change != "NEW"
            assert proposal.changes[0].generated_sku is False
    finally:
        await world.app.state.engine.dispose()


@pytest.mark.asyncio
async def test_linha_sem_sku_usa_familia_para_desempatar_nome_repetido():
    world = await build_portal_world()
    try:
        async with world.app.state.session_factory() as session:
            original = await session.get(Product, world.product_id)
            original_family = await session.get(ProductFamily, original.family_id)
            other_family = ProductFamily(
                tenant_id=world.tenant_id,
                name="Outra familia",
                display_order=999,
            )
            session.add(other_family)
            await session.flush()
            session.add(
                Product(
                    tenant_id=world.tenant_id,
                    family_id=other_family.id,
                    sku="OUTRO-SKU-MESMO-NOME",
                    commercial_name=original.commercial_name,
                    unit="KG",
                )
            )
            await session.flush()

            proposal = await RepresentativePriceUpdateService(session).propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.generated-family-match",
                reference_month=date(2026, 11, 1),
                rows=[
                    ProposedPriceRow(
                        sku="AUTO-FAMILY-MATCH",
                        generated_sku=True,
                        commercial_name=original.commercial_name,
                        family_name=original_family.name,
                        base_price=Decimal("14.38"),
                    )
                ],
            )

            assert proposal.ready_for_confirmation is True
            assert proposal.changes[0].sku == original.sku
            assert proposal.changes[0].change != "NEW"
            assert proposal.changes[0].generated_sku is False
    finally:
        await world.app.state.engine.dispose()


@pytest.mark.asyncio
async def test_confirmacao_consolida_duas_linhas_equivalentes_no_mesmo_produto():
    world = await build_portal_world()
    try:
        async with world.app.state.session_factory() as session:
            product = await session.get(Product, world.product_id)
            family = await session.get(ProductFamily, product.family_id)
            proposal = await RepresentativePriceUpdateService(session).propose(
                tenant_id=world.tenant_id,
                representative_user_id=world.representative_a_id,
                source_wamid="wamid.duplicate-product-match",
                reference_month=date(2026, 11, 1),
                rows=[
                    ProposedPriceRow(
                        sku="AUTO-DUPLICATE-1",
                        generated_sku=True,
                        commercial_name=product.commercial_name,
                        family_name=family.name,
                        availability=AvailabilityStatus.SUSPENDED,
                    ),
                    ProposedPriceRow(
                        sku="AUTO-DUPLICATE-2",
                        generated_sku=True,
                        commercial_name=product.commercial_name.upper(),
                        family_name=family.name.upper(),
                        availability=AvailabilityStatus.SUSPENDED,
                    ),
                ],
            )
            await session.commit()

        async with world.app.state.session_factory() as session:
            service = RepresentativePriceUpdateService(session)
            batch = await service.get_owned(
                world.tenant_id, world.representative_a_id, proposal.proposal_id
            )
            await service.materialize_for_confirmation(
                batch,
                actor_user_id=world.representative_a_id,
                request_id="wamid.duplicate-product-match.confirm",
            )
            items = list(
                await session.scalars(
                    select(PriceListItem).where(PriceListItem.price_list_id == batch.id)
                )
            )
            assert len(items) == 1
            assert items[0].availability is AvailabilityStatus.SUSPENDED
    finally:
        await world.app.state.engine.dispose()
