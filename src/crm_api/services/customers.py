import re

from crm_api.repositories.customers import CustomerRepository
from crm_api.schemas.customers import CustomerContactResponse

_PRESENTATION_CHARS = re.compile(r"[\s().-]")
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")


class InvalidWhatsappNumber(ValueError):
    pass


def normalize_whatsapp_e164(phone: str) -> str:
    normalized = _PRESENTATION_CHARS.sub("", phone)
    if not _E164.fullmatch(normalized):
        raise InvalidWhatsappNumber("phone must be a valid E.164 number")
    return normalized


class CustomerService:
    def __init__(self, repository: CustomerRepository):
        self._repository = repository

    async def find_active_by_whatsapp(
        self, tenant_slug: str, phone: str
    ) -> CustomerContactResponse | None:
        contact_and_customer = await self._repository.get_active_by_whatsapp(tenant_slug, phone)
        if contact_and_customer is None:
            return None
        contact, customer = contact_and_customer
        return CustomerContactResponse(
            customer_id=customer.id,
            customer_name=customer.legal_name,
            state_code=customer.state_code,
            contact_id=contact.id,
            contact_name=contact.name,
            whatsapp_e164=contact.whatsapp_e164,
        )
