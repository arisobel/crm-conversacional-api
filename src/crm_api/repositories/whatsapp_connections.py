import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.whatsapp_connection import (
    RepresentativeWhatsappConnection,
    WhatsappConnectionStatus,
)


class WhatsappConnectionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_for_representative(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> RepresentativeWhatsappConnection | None:
        return await self._session.scalar(
            select(RepresentativeWhatsappConnection)
            .where(
                RepresentativeWhatsappConnection.tenant_id == tenant_id,
                RepresentativeWhatsappConnection.representative_user_id == user_id,
            )
            .order_by(RepresentativeWhatsappConnection.created_at.desc())
        )

    async def get_by_id(
        self, tenant_id: uuid.UUID, connection_id: uuid.UUID
    ) -> RepresentativeWhatsappConnection | None:
        return await self._session.scalar(
            select(RepresentativeWhatsappConnection).where(
                RepresentativeWhatsappConnection.tenant_id == tenant_id,
                RepresentativeWhatsappConnection.id == connection_id,
            )
        )

    def add(self, connection: RepresentativeWhatsappConnection) -> None:
        self._session.add(connection)

    @staticmethod
    def active(status: WhatsappConnectionStatus) -> bool:
        return status in {
            WhatsappConnectionStatus.CONNECTING,
            WhatsappConnectionStatus.CONNECTED,
            WhatsappConnectionStatus.ACTION_REQUIRED,
        }
