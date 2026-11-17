import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.user import RepresentativeInvite, RepresentativeInviteStatus


class RepresentativeInviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, invite: RepresentativeInvite) -> None:
        self._session.add(invite)

    async def get_by_token_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> RepresentativeInvite | None:
        statement = select(RepresentativeInvite).where(
            RepresentativeInvite.token_hash == token_hash
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def count_pending(self, tenant_id: uuid.UUID) -> int:
        from sqlalchemy import func

        return int(
            await self._session.scalar(
                select(func.count(RepresentativeInvite.id)).where(
                    RepresentativeInvite.tenant_id == tenant_id,
                    RepresentativeInvite.status == RepresentativeInviteStatus.PENDING,
                )
            )
            or 0
        )
