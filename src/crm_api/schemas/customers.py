from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CustomerContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: UUID
    customer_name: str
    state_code: str
    contact_id: UUID
    contact_name: str
    whatsapp_e164: str

