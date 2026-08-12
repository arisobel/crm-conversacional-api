from datetime import datetime
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


class AuthorizedContactsResponse(BaseModel):
    """Lista completa de quem pode conversar, para o Gateway espelhar.

    Carrega telefone e mais nada. Nome, cliente e localidade continuam do lado
    do CRM: o Gateway decide se atende, não monta ficha.
    """

    contacts: list[str]
    count: int
    # Digest da lista ordenada. Igual ao anterior significa que nada mudou e a
    # reconciliação inteira pode ser pulada.
    etag: str
    generated_at: datetime

