import hashlib
import re
from datetime import UTC, datetime

from crm_api.repositories.customers import CustomerRepository
from crm_api.schemas.customers import AuthorizedContactsResponse, CustomerContactResponse

_PRESENTATION_CHARS = re.compile(r"[\s().-]")
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")

# Teto do roster. A lista é devolvida inteira, sem paginação, porque o Gateway
# deduz desativação por ausência: uma lista parcial faria ele desativar contatos
# que continuam válidos. Estourar o teto é erro explícito, não truncamento — o
# dia em que acontecer, alguém implementa um protocolo incremental de propósito.
_MAX_ROSTER = 10_000


class InvalidWhatsappNumber(ValueError):
    pass


class RosterTooLarge(Exception):
    """Carteira maior que o teto do roster de uma resposta só."""


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

    async def authorized_contacts(self, tenant_slug: str) -> AuthorizedContactsResponse:
        telefones = await self._repository.list_active_whatsapp(tenant_slug)
        if len(telefones) > _MAX_ROSTER:
            raise RosterTooLarge(
                f"{len(telefones)} contatos ativos excedem o limite de {_MAX_ROSTER}"
            )
        digest = hashlib.sha256("\n".join(telefones).encode("utf-8")).hexdigest()
        return AuthorizedContactsResponse(
            contacts=telefones,
            count=len(telefones),
            etag=digest,
            generated_at=datetime.now(UTC),
        )
