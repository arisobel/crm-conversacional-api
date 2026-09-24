from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from crm_api.models.whatsapp_connection import WhatsappConnectionStatus
from crm_api.services.whatsapp_connections import ConnectionRetryAction


class WhatsappConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    connection_id: UUID
    representative_user_id: UUID
    status: WhatsappConnectionStatus
    display_phone_number: str | None
    failure_code: str | None
    started_at: datetime | None
    connected_at: datetime | None
    launch_url: str | None = None
    retry_action: ConnectionRetryAction = ConnectionRetryAction.NONE
