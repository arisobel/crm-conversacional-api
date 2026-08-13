import hashlib
import re
from datetime import UTC, datetime

from crm_api.repositories.customers import CustomerRepository
from crm_api.schemas.customers import AuthorizedContactsResponse, CustomerContactResponse

_PRESENTATION_CHARS = re.compile(r"[\s().-]")
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
# Celular brasileiro na forma anterior à renumeração de 2012: +55, DDD e oito
# dígitos começando em 6-9. Fixo começa em 2-5 e não recebe nono dígito —
# WhatsApp Business pode usar linha fixa, então a distinção não é acadêmica.
_BR_MOBILE_WITHOUT_NINTH = re.compile(r"^\+55([1-9][0-9])([6-9][0-9]{7})$")

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
    """Forma canônica de telefone: E.164 com "+" e nono dígito aplicado.

    O nono dígito não é formatação, é identidade: `+551188887777` e
    `+5511988887777` são o mesmo assinante, e contas antigas ainda chegam da
    Meta sem ele. Sem resolver as duas grafias para a mesma, um cliente
    cadastrado numa forma e escrevendo da outra não é encontrado — e o cadastro
    aparece correto na tela, sem nada a depurar.
    """
    normalized = _PRESENTATION_CHARS.sub("", phone)
    if not _E164.fullmatch(normalized):
        raise InvalidWhatsappNumber("phone must be a valid E.164 number")
    antiga = _BR_MOBILE_WITHOUT_NINTH.fullmatch(normalized)
    if antiga:
        return f"+55{antiga.group(1)}9{antiga.group(2)}"
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
