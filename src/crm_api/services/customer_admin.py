"""Cadastro comercial operado pelo portal: cliente, contatos e localidades."""

import uuid
from datetime import UTC, datetime

from crm_api.core.states import normalize_state_code
from crm_api.models.customer import Customer, CustomerAssignmentHistory, CustomerLocation
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.customer_admin import CustomerAdminRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository, PortfolioScope
from crm_api.services.customers import normalize_whatsapp_e164
from crm_api.services.portfolio import CustomerNotInScope

_DEFAULT_LOCATION_LABEL = "Principal"


class DuplicateDocument(Exception):
    """Já existe cliente com este documento no tenant."""


class DuplicateWhatsapp(Exception):
    """Já existe contato com este telefone no tenant."""


class ContactNotFound(Exception):
    """Contato inexistente neste cliente."""


class LocationNotFound(Exception):
    """Localidade inexistente neste cliente."""


class DefaultLocationRequired(Exception):
    """A operação deixaria o cliente sem localidade padrão ativa."""


class CustomerAdminService:
    def __init__(
        self,
        *,
        portfolio: CustomerPortfolioRepository,
        admin: CustomerAdminRepository,
        audit: AuditRepository,
    ) -> None:
        self._portfolio = portfolio
        self._admin = admin
        self._audit = audit

    async def _customer_in_scope(
        self, scope: PortfolioScope, customer_id: uuid.UUID
    ) -> Customer:
        found = await self._portfolio.get_customer(scope, customer_id)
        if found is None:
            raise CustomerNotInScope
        return found[0]

    # ---------------------------------------------------------------- cliente

    async def create_customer(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_role: UserRole,
        legal_name: str,
        state_code: str,
        trade_name: str | None = None,
        document_number: str | None = None,
        owner_user_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> Customer:
        """Cria o cliente e a sua localidade padrão na mesma transação.

        A localidade nasce junto porque todo o cálculo de ICMS (R4) parte dela;
        um cliente sem localidade padrão seria um cadastro que não precifica.
        """
        normalized_state = normalize_state_code(state_code)
        document = document_number.strip() if document_number else None
        if document and await self._admin.document_exists(tenant_id, document):
            raise DuplicateDocument

        # Um representante só cria clientes para a própria carteira; escolher
        # outro titular é privilégio de ADMIN e MANAGER.
        owner = (
            actor_user_id if actor_role is UserRole.REPRESENTATIVE else owner_user_id
        )

        customer = Customer(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            legal_name=legal_name.strip(),
            trade_name=trade_name.strip() if trade_name else None,
            document_number=document,
            state_code=normalized_state,
            owner_user_id=owner,
        )
        self._admin.add(customer)
        self._admin.add(
            CustomerLocation(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                customer_id=customer.id,
                label=_DEFAULT_LOCATION_LABEL,
                state_code=normalized_state,
                is_default=True,
            )
        )
        if owner is not None:
            self._admin.add(
                CustomerAssignmentHistory(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    customer_id=customer.id,
                    user_id=owner,
                    assigned_by=actor_user_id,
                    reason="cadastro inicial",
                )
            )
        self._audit.record(
            action="CUSTOMER_CREATED",
            entity="customers",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=customer.id,
            after={
                "legal_name": customer.legal_name,
                "state_code": normalized_state,
                "owner_user_id": str(owner) if owner else None,
            },
            request_id=request_id,
        )
        return customer

    async def update_customer(
        self,
        scope: PortfolioScope,
        customer_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        legal_name: str | None = None,
        trade_name: str | None = None,
        document_number: str | None = None,
        state_code: str | None = None,
        active: bool | None = None,
        request_id: str | None = None,
    ) -> Customer:
        customer = await self._customer_in_scope(scope, customer_id)
        before = {
            "legal_name": customer.legal_name,
            "trade_name": customer.trade_name,
            "document_number": customer.document_number,
            "state_code": customer.state_code,
            "active": customer.active,
        }

        if document_number is not None:
            document = document_number.strip() or None
            if document and await self._admin.document_exists(
                scope.tenant_id, document, excluding=customer.id
            ):
                raise DuplicateDocument
            customer.document_number = document
        if state_code is not None:
            customer.state_code = normalize_state_code(state_code)
        if legal_name is not None:
            customer.legal_name = legal_name.strip()
        if trade_name is not None:
            customer.trade_name = trade_name.strip() or None
        if active is not None:
            customer.active = active
        customer.updated_at = datetime.now(UTC)

        self._audit.record(
            action="CUSTOMER_UPDATED",
            entity="customers",
            tenant_id=scope.tenant_id,
            actor_user_id=actor_user_id,
            entity_id=customer.id,
            before=before,
            after={
                "legal_name": customer.legal_name,
                "trade_name": customer.trade_name,
                "document_number": customer.document_number,
                "state_code": customer.state_code,
                "active": customer.active,
            },
            request_id=request_id,
        )
        return customer

    # --------------------------------------------------------------- contatos

    async def list_contacts(
        self, scope: PortfolioScope, customer_id: uuid.UUID
    ) -> list[CustomerContact]:
        await self._customer_in_scope(scope, customer_id)
        return await self._admin.list_contacts(customer_id)

    async def create_contact(
        self,
        scope: PortfolioScope,
        customer_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        name: str,
        whatsapp_e164: str,
        is_primary: bool = False,
        request_id: str | None = None,
    ) -> CustomerContact:
        await self._customer_in_scope(scope, customer_id)
        phone = normalize_whatsapp_e164(whatsapp_e164)
        if await self._admin.whatsapp_exists(scope.tenant_id, phone):
            raise DuplicateWhatsapp

        if is_primary:
            await self._admin.clear_primary_contact(customer_id)

        contact = CustomerContact(
            id=uuid.uuid4(),
            tenant_id=scope.tenant_id,
            customer_id=customer_id,
            name=name.strip(),
            whatsapp_e164=phone,
            is_primary=is_primary,
        )
        self._admin.add(contact)
        self._audit.record(
            action="CUSTOMER_CONTACT_CREATED",
            entity="customer_contacts",
            tenant_id=scope.tenant_id,
            actor_user_id=actor_user_id,
            entity_id=contact.id,
            after={"customer_id": str(customer_id), "is_primary": is_primary},
            request_id=request_id,
        )
        return contact

    async def update_contact(
        self,
        scope: PortfolioScope,
        customer_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        name: str | None = None,
        whatsapp_e164: str | None = None,
        is_primary: bool | None = None,
        active: bool | None = None,
        request_id: str | None = None,
    ) -> CustomerContact:
        await self._customer_in_scope(scope, customer_id)
        contact = await self._admin.get_contact(customer_id, contact_id)
        if contact is None:
            raise ContactNotFound

        before = {
            "name": contact.name,
            "whatsapp_e164": contact.whatsapp_e164,
            "is_primary": contact.is_primary,
            "active": contact.active,
        }

        if whatsapp_e164 is not None:
            phone = normalize_whatsapp_e164(whatsapp_e164)
            if await self._admin.whatsapp_exists(scope.tenant_id, phone, excluding=contact.id):
                raise DuplicateWhatsapp
            contact.whatsapp_e164 = phone
        if name is not None:
            contact.name = name.strip()
        if is_primary is not None:
            if is_primary:
                await self._admin.clear_primary_contact(customer_id, excluding=contact.id)
            contact.is_primary = is_primary
        if active is not None:
            contact.active = active
            # Um contato desativado não pode continuar sendo o principal: o
            # índice tolera, mas a ficha passaria a exibir alguém inalcançável.
            if not active:
                contact.is_primary = False

        self._audit.record(
            action="CUSTOMER_CONTACT_UPDATED",
            entity="customer_contacts",
            tenant_id=scope.tenant_id,
            actor_user_id=actor_user_id,
            entity_id=contact.id,
            before=before,
            after={
                "name": contact.name,
                "whatsapp_e164": contact.whatsapp_e164,
                "is_primary": contact.is_primary,
                "active": contact.active,
            },
            request_id=request_id,
        )
        return contact

    # ------------------------------------------------------------ localidades

    async def list_locations(
        self, scope: PortfolioScope, customer_id: uuid.UUID
    ) -> list[CustomerLocation]:
        await self._customer_in_scope(scope, customer_id)
        return await self._admin.list_locations(customer_id)

    async def create_location(
        self,
        scope: PortfolioScope,
        customer_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        label: str,
        state_code: str,
        city: str | None = None,
        is_default: bool = False,
        request_id: str | None = None,
    ) -> CustomerLocation:
        await self._customer_in_scope(scope, customer_id)
        normalized_state = normalize_state_code(state_code)

        # Se o cliente ainda não tem padrão ativa, esta assume o posto: é
        # preferível a um cadastro que não precifica.
        becomes_default = is_default or (
            await self._admin.get_default_location(customer_id) is None
        )
        if becomes_default:
            await self._admin.clear_default_location(customer_id)

        location = CustomerLocation(
            id=uuid.uuid4(),
            tenant_id=scope.tenant_id,
            customer_id=customer_id,
            label=label.strip(),
            state_code=normalized_state,
            city=city.strip() if city else None,
            is_default=becomes_default,
        )
        self._admin.add(location)
        self._audit.record(
            action="CUSTOMER_LOCATION_CREATED",
            entity="customer_locations",
            tenant_id=scope.tenant_id,
            actor_user_id=actor_user_id,
            entity_id=location.id,
            after={
                "customer_id": str(customer_id),
                "state_code": normalized_state,
                "is_default": becomes_default,
            },
            request_id=request_id,
        )
        return location

    async def update_location(
        self,
        scope: PortfolioScope,
        customer_id: uuid.UUID,
        location_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        label: str | None = None,
        state_code: str | None = None,
        city: str | None = None,
        is_default: bool | None = None,
        active: bool | None = None,
        request_id: str | None = None,
    ) -> CustomerLocation:
        await self._customer_in_scope(scope, customer_id)
        location = await self._admin.get_location(customer_id, location_id)
        if location is None:
            raise LocationNotFound

        before = {
            "label": location.label,
            "state_code": location.state_code,
            "city": location.city,
            "is_default": location.is_default,
            "active": location.active,
        }

        if active is False and location.is_default:
            # Promover outra localidade primeiro é uma escolha comercial; o
            # sistema não elege sozinho para onde a mercadoria passa a ir.
            raise DefaultLocationRequired(
                "promote another location to default before deactivating this one"
            )
        if is_default is False and location.is_default:
            raise DefaultLocationRequired("set another location as default instead")

        if state_code is not None:
            location.state_code = normalize_state_code(state_code)
        if label is not None:
            location.label = label.strip()
        if city is not None:
            location.city = city.strip() or None
        if is_default:
            await self._admin.clear_default_location(customer_id, excluding=location.id)
            location.is_default = True
            location.active = True
        if active is not None:
            location.active = active
        location.updated_at = datetime.now(UTC)

        self._audit.record(
            action="CUSTOMER_LOCATION_UPDATED",
            entity="customer_locations",
            tenant_id=scope.tenant_id,
            actor_user_id=actor_user_id,
            entity_id=location.id,
            before=before,
            after={
                "label": location.label,
                "state_code": location.state_code,
                "city": location.city,
                "is_default": location.is_default,
                "active": location.active,
            },
            request_id=request_id,
        )
        return location
