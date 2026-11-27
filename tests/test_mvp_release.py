from datetime import UTC, datetime

import pytest
from conftest import ADMIN_EMAIL, build_portal_world
from sqlalchemy import select

from crm_api.models.assistant_settings import (
    ConversationSimulationScenario,
    MvpReleaseControl,
)
from crm_api.models.user import User
from crm_api.services.assistant_monitoring import assistant_monitoring_snapshot
from crm_api.services.mvp_release import (
    MVP_E2E_CHECKS,
    release_gate,
    scope_hash,
    scope_snapshot,
)


@pytest.mark.asyncio
async def test_gate_so_libera_com_todas_as_evidencias_e_escopo_intacto():
    world = await build_portal_world()
    try:
        async with world.app.state.session_factory() as session:
            admin_id = await session.scalar(select(User.id).where(User.email == ADMIN_EMAIL))
            scenario = ConversationSimulationScenario(
                tenant_id=world.tenant_id,
                name="Fluxo principal aprovado",
                mode="REPRESENTATIVE_ASSISTANT",
                representative_user_id=world.representative_a_id,
                message="Liste minha carteira",
                expected_status="RESOLVED",
                last_passed=True,
                last_result="aprovado",
                last_run_at=datetime.now(UTC),
                created_by_user_id=admin_id,
            )
            session.add(scenario)
            await session.flush()
            snapshot = await scope_snapshot(session, world.tenant_id)
            session.add(
                MvpReleaseControl(
                    tenant_id=world.tenant_id,
                    scope_version="MVP-TESTE",
                    scope_frozen_at=datetime.now(UTC),
                    scope_frozen_by_user_id=admin_id,
                    scope_snapshot_hash=scope_hash(snapshot),
                    scope_snapshot=snapshot,
                    acceptance_checks={
                        check_id: {"status": "PASS", "note": "Executado no WhatsApp."}
                        for check_id, _ in MVP_E2E_CHECKS
                    },
                )
            )
            await session.commit()

            monitoring = await assistant_monitoring_snapshot(session, world.tenant_id)
            gate = await release_gate(
                session,
                world.tenant_id,
                monitoring=monitoring,
                gateway_status={
                    "features": {
                        "voice_transcription": True,
                        "natural_replies": True,
                        "automatic_handoff": True,
                    },
                    "interaction_outbox": {
                        "persistent": True,
                        "available": True,
                        "pending": 0,
                        "failed": 0,
                    },
                },
            )

        assert gate.ready is True
        assert gate.status == "READY"
        assert all(item.passed for item in gate.items)
    finally:
        await world.app.state.engine.dispose()
