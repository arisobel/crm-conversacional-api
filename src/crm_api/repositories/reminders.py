import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.reminder import RepresentativeReminder


class ReminderRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_source(
        self, tenant_id: uuid.UUID, source_wamid: str
    ) -> RepresentativeReminder | None:
        return await self._session.scalar(
            select(RepresentativeReminder).where(
                RepresentativeReminder.tenant_id == tenant_id,
                RepresentativeReminder.source_wamid == source_wamid,
            )
        )

    def add(self, reminder: RepresentativeReminder) -> None:
        self._session.add(reminder)

    async def find_slot_conflict(
        self,
        tenant_id: uuid.UUID,
        representative_user_id: uuid.UUID,
        slot_start: datetime,
        slot_end: datetime,
        excluding: uuid.UUID | None = None,
    ) -> RepresentativeReminder | None:
        """Encontra outro compromisso ativo dentro da mesma hora comercial."""
        statement = (
            select(RepresentativeReminder)
            .where(
                RepresentativeReminder.tenant_id == tenant_id,
                RepresentativeReminder.representative_user_id == representative_user_id,
                RepresentativeReminder.status.in_(("PENDING_CONFIRMATION", "CONFIRMED")),
                RepresentativeReminder.due_at >= slot_start,
                RepresentativeReminder.due_at < slot_end,
            )
            .order_by(RepresentativeReminder.due_at, RepresentativeReminder.id)
        )
        if excluding is not None:
            statement = statement.where(RepresentativeReminder.id != excluding)
        return await self._session.scalar(statement.limit(1))

    async def list_upcoming(
        self,
        tenant_id: uuid.UUID,
        representative_user_id: uuid.UUID,
        now: datetime,
        *,
        customer_id: uuid.UUID | None = None,
        limit: int = 20,
    ) -> list[RepresentativeReminder]:
        statement = select(RepresentativeReminder).where(
            RepresentativeReminder.tenant_id == tenant_id,
            RepresentativeReminder.representative_user_id == representative_user_id,
            RepresentativeReminder.status.in_(("PENDING_CONFIRMATION", "CONFIRMED")),
            RepresentativeReminder.due_at >= now,
        )
        if customer_id is not None:
            statement = statement.where(RepresentativeReminder.customer_id == customer_id)
        statement = statement.order_by(
            RepresentativeReminder.due_at, RepresentativeReminder.id
        ).limit(limit)
        rows = await self._session.scalars(
            statement
        )
        return list(rows)

    async def get_for_representative(
        self,
        tenant_id: uuid.UUID,
        representative_user_id: uuid.UUID,
        reminder_id: uuid.UUID,
    ) -> RepresentativeReminder | None:
        return await self._session.scalar(
            select(RepresentativeReminder).where(
                RepresentativeReminder.id == reminder_id,
                RepresentativeReminder.tenant_id == tenant_id,
                RepresentativeReminder.representative_user_id == representative_user_id,
            )
        )

    async def due(self, now: datetime, *, limit: int = 100) -> list[RepresentativeReminder]:
        rows = await self._session.scalars(
            select(RepresentativeReminder)
            .where(
                RepresentativeReminder.status.in_(("PENDING_CONFIRMATION", "CONFIRMED")),
                RepresentativeReminder.notified_at.is_(None),
                RepresentativeReminder.due_at <= now,
            )
            .order_by(RepresentativeReminder.due_at, RepresentativeReminder.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows)

