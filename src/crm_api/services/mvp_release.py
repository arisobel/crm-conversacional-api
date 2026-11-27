"""Gate objetivo de liberacao e congelamento do escopo do MVP."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.assistant_settings import (
    AssistantOrganizationSettings,
    AssistantRepresentativeCapability,
    AssistantRepresentativeSettings,
    ConversationBehaviorSettings,
    ConversationSimulationScenario,
    MvpReleaseControl,
)
from crm_api.services.assistant_monitoring import AssistantMonitoringSnapshot

MVP_E2E_CHECKS: tuple[tuple[str, str], ...] = (
    ("LINE_ROUTING", "Separação entre linha de clientes e linha do representante"),
    ("CUSTOMER_SERVICE", "Atendimento real de cliente no WhatsApp"),
    ("REPRESENTATIVE_ASSISTANT", "Assistente real do representante"),
    ("AUDIO", "Áudio transcrito e compreendido"),
    ("REMINDERS", "Lembrete criado e entregue no horário"),
    ("CUSTOMER_INTAKE", "Pré-cadastro criado e encaminhado para conferência"),
    ("PRICE_UPDATE", "Tabela revisada, confirmada e publicada"),
    ("HUMAN_HANDOFF", "Transferencia humana sem resposta simultanea do robo"),
    ("ONBOARDING", "Convite e conexão do representante concluídos"),
    ("RESTART_RECOVERY", "Reinício sem perda de eventos pendentes"),
)
_CHECK_IDS = frozenset(check_id for check_id, _ in MVP_E2E_CHECKS)
_CHECK_STATUSES = frozenset({"PENDING", "PASS", "FAIL"})


@dataclass(frozen=True)
class ReleaseGateItem:
    key: str
    label: str
    passed: bool
    detail: str
    critical: bool = False


@dataclass(frozen=True)
class ReleaseGate:
    status: str
    ready: bool
    items: tuple[ReleaseGateItem, ...]
    control: MvpReleaseControl | None
    checks: tuple[dict[str, str], ...]
    scope_drifted: bool
    current_scope_hash: str


def normalize_acceptance_check(
    check_id: str, status: str, note: str, *, updated_at: datetime, updated_by: uuid.UUID
) -> dict[str, str]:
    if check_id not in _CHECK_IDS or status not in _CHECK_STATUSES:
        raise ValueError("invalid acceptance check")
    clean_note = note.strip()[:500]
    if status in {"PASS", "FAIL"} and not clean_note:
        raise ValueError("evidence note is required")
    return {
        "status": status,
        "note": clean_note,
        "updated_at": updated_at.isoformat(),
        "updated_by": str(updated_by),
    }


async def scope_snapshot(session: AsyncSession, tenant_id: uuid.UUID) -> dict:
    organization = await session.get(AssistantOrganizationSettings, tenant_id)
    representatives = list(
        await session.scalars(
            select(AssistantRepresentativeSettings)
            .where(AssistantRepresentativeSettings.tenant_id == tenant_id)
            .order_by(AssistantRepresentativeSettings.user_id)
        )
    )
    capabilities = list(
        await session.scalars(
            select(AssistantRepresentativeCapability)
            .where(AssistantRepresentativeCapability.tenant_id == tenant_id)
            .order_by(
                AssistantRepresentativeCapability.user_id,
                AssistantRepresentativeCapability.capability_id,
            )
        )
    )
    behaviors = list(
        await session.scalars(
            select(ConversationBehaviorSettings)
            .where(ConversationBehaviorSettings.tenant_id == tenant_id)
            .order_by(ConversationBehaviorSettings.bot_kind)
        )
    )
    scenarios = list(
        await session.scalars(
            select(ConversationSimulationScenario)
            .where(
                ConversationSimulationScenario.tenant_id == tenant_id,
                ConversationSimulationScenario.active.is_(True),
            )
            .order_by(ConversationSimulationScenario.id)
        )
    )
    return {
        "organization_enabled": bool(organization and organization.enabled),
        "representatives": [
            {"user_id": str(item.user_id), "enabled": item.enabled} for item in representatives
        ],
        "capabilities": [
            {"user_id": str(item.user_id), "capability_id": item.capability_id}
            for item in capabilities
        ],
        "behaviors": [
            {
                "bot_kind": item.bot_kind,
                "tone": item.tone,
                "instructions": item.instructions,
                "context_minutes": item.context_minutes,
            }
            for item in behaviors
        ],
        "scenarios": [
            {
                "id": str(item.id),
                "name": item.name,
                "mode": item.mode,
                "message": item.message,
                "expected_status": item.expected_status,
                "expected_capability_id": item.expected_capability_id,
                "expected_action": item.expected_action,
                "expected_fact_text": item.expected_fact_text,
                "expected_reply_contains": item.expected_reply_contains,
                "forbidden_reply_contains": item.forbidden_reply_contains,
                "max_questions": item.max_questions,
            }
            for item in scenarios
        ],
    }


def scope_hash(snapshot: dict) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def release_gate(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    monitoring: AssistantMonitoringSnapshot,
    gateway_status: dict | None,
) -> ReleaseGate:
    control = await session.get(MvpReleaseControl, tenant_id)
    snapshot = await scope_snapshot(session, tenant_id)
    current_hash = scope_hash(snapshot)
    saved_checks = control.acceptance_checks if control else {}
    checks = tuple(
        {
            "id": check_id,
            "label": label,
            "status": str((saved_checks.get(check_id) or {}).get("status") or "PENDING"),
            "note": str((saved_checks.get(check_id) or {}).get("note") or ""),
        }
        for check_id, label in MVP_E2E_CHECKS
    )
    scenarios = list(
        await session.scalars(
            select(ConversationSimulationScenario).where(
                ConversationSimulationScenario.tenant_id == tenant_id,
                ConversationSimulationScenario.active.is_(True),
            )
        )
    )
    features = (gateway_status or {}).get("features") or {}
    outbox = (gateway_status or {}).get("interaction_outbox") or {}
    scope_frozen = bool(control and control.scope_snapshot_hash)
    scope_drifted = bool(scope_frozen and control.scope_snapshot_hash != current_hash)
    all_checks_passed = all(item["status"] == "PASS" for item in checks)
    scenarios_passed = bool(scenarios) and all(
        item.last_run_at is not None and item.last_passed is True for item in scenarios
    )
    items = (
        ReleaseGateItem(
            "gateway",
            "Gateway acessível",
            gateway_status is not None,
            "Online" if gateway_status else "Sem resposta do Gateway",
            True,
        ),
        ReleaseGateItem(
            "features",
            "Recursos essenciais ativos",
            all(
                features.get(key) is True
                for key in ("voice_transcription", "natural_replies", "automatic_handoff")
            ),
            "Voz, respostas naturais e transferência humana",
            True,
        ),
        ReleaseGateItem(
            "outbox",
            "Fila critica persistente",
            outbox.get("persistent") is True
            and outbox.get("available") is True
            and int(outbox.get("pending") or 0) == 0
            and int(outbox.get("failed") or 0) == 0,
            (
                f"{int(outbox.get('pending') or 0)} pendente(s), "
                f"{int(outbox.get('failed') or 0)} falha(s)"
                if outbox
                else "Gateway ainda nao informou a fila persistente"
            ),
            True,
        ),
        ReleaseGateItem(
            "operations",
            "Sem pendências operacionais críticas",
            monitoring.overdue_reminders == 0 and monitoring.stale_pending_intakes == 0,
            f"{monitoring.overdue_reminders} lembrete(s) atrasado(s); "
            f"{monitoring.stale_pending_intakes} pré-cadastro(s) parado(s)",
        ),
        ReleaseGateItem(
            "scenarios",
            "Regressão automatizada aprovada",
            scenarios_passed,
            (
                f"{sum(item.last_passed is True for item in scenarios)}/"
                f"{len(scenarios)} cenário(s) aprovado(s)"
            ),
        ),
        ReleaseGateItem(
            "e2e",
            "Validação real ponta a ponta",
            all_checks_passed,
            (
                f"{sum(item['status'] == 'PASS' for item in checks)}/"
                f"{len(checks)} evidência(s) aprovada(s)"
            ),
        ),
        ReleaseGateItem(
            "scope",
            "Escopo congelado sem alterações",
            scope_frozen and not scope_drifted,
            "Escopo intacto"
            if scope_frozen and not scope_drifted
            else (
                "O escopo mudou depois do congelamento"
                if scope_drifted
                else "Escopo ainda não congelado"
            ),
            True,
        ),
    )
    ready = all(item.passed for item in items)
    status = (
        "READY"
        if ready
        else (
            "BLOCKED" if any(item.critical and not item.passed for item in items) else "ATTENTION"
        )
    )
    return ReleaseGate(status, ready, items, control, checks, scope_drifted, current_hash)
