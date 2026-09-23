import uuid
from datetime import UTC, datetime

from crm_api.models.user import User, UserRole
from crm_api.models.whatsapp_connection import (
    RepresentativeWhatsappConnection,
    WhatsappConnectionStatus,
)
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.users import UserRepository
from crm_api.repositories.whatsapp_connections import WhatsappConnectionRepository
from crm_api.services.gateway_whatsapp_onboarding import (
    GatewayOnboarding,
    GatewayWhatsappOnboardingClient,
)


class ConnectionNotFound(Exception):
    pass


class ConnectionForbidden(Exception):
    pass


class ConnectionConflict(Exception):
    pass


_MAP = {
    "AUTHORIZATION_PENDING": WhatsappConnectionStatus.CONNECTING,
    "TOKEN_EXCHANGE_PENDING": WhatsappConnectionStatus.CONNECTING,
    "TOKEN_RECEIVED": WhatsappConnectionStatus.CONNECTING,
    "ASSET_DISCOVERY_PENDING": WhatsappConnectionStatus.CONNECTING,
    "ASSET_DISCOVERED": WhatsappConnectionStatus.CONNECTING,
    "SUBSCRIPTION_PENDING": WhatsappConnectionStatus.CONNECTING,
    "PROVISIONING": WhatsappConnectionStatus.CONNECTING,
    "COMPLETED": WhatsappConnectionStatus.CONNECTED,
    "ACTION_REQUIRED": WhatsappConnectionStatus.ACTION_REQUIRED,
    "CONFLICT": WhatsappConnectionStatus.CONFLICT,
    "FAILED": WhatsappConnectionStatus.FAILED,
}


class WhatsappConnectionService:
    def __init__(
        self,
        *,
        connections: WhatsappConnectionRepository,
        users: UserRepository,
        audit: AuditRepository,
        gateway: GatewayWhatsappOnboardingClient,
    ) -> None:
        self._connections, self._users, self._audit, self._gateway = (
            connections,
            users,
            audit,
            gateway,
        )

    async def _representative(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
        user = await self._users.get_in_tenant(tenant_id, user_id)
        if user is None or user.role is not UserRole.REPRESENTATIVE or not user.active:
            raise ConnectionNotFound
        return user

    def _authorized(
        self, actor_id: uuid.UUID, role: UserRole, representative_id: uuid.UUID
    ) -> None:
        if role is UserRole.REPRESENTATIVE and actor_id != representative_id:
            raise ConnectionForbidden

    def _apply(self, connection: RepresentativeWhatsappConnection, data: GatewayOnboarding) -> bool:
        old = connection.status
        connection.last_gateway_status = data.status
        connection.status = _MAP.get(data.status, WhatsappConnectionStatus.FAILED)
        connection.failure_code = data.failure_code
        if data.display_phone_number:
            connection.display_phone_number = data.display_phone_number
        if data.gateway_line_reference:
            connection.gateway_line_reference = data.gateway_line_reference
        now = datetime.now(UTC)
        if (
            connection.status is WhatsappConnectionStatus.CONNECTED
            and connection.connected_at is None
        ):
            connection.connected_at = now
        if (
            connection.status
            in {WhatsappConnectionStatus.FAILED, WhatsappConnectionStatus.CONFLICT}
            and connection.failed_at is None
        ):
            connection.failed_at = now
        connection.updated_at = now
        return old != connection.status

    def _audit_event(
        self,
        connection: RepresentativeWhatsappConnection,
        actor_id: uuid.UUID,
        action: str,
        request_id: str | None,
    ) -> None:
        self._audit.record(
            action=action,
            entity="representative_whatsapp_connections",
            tenant_id=connection.tenant_id,
            actor_user_id=actor_id,
            entity_id=connection.id,
            after={
                "representative_user_id": str(connection.representative_user_id),
                "gateway_onboarding_id": connection.gateway_onboarding_id,
                "status": connection.status.value,
            },
            request_id=request_id,
        )

    async def get(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        role: UserRole,
        representative_id: uuid.UUID,
        refresh: bool = True,
        request_id: str | None = None,
    ) -> RepresentativeWhatsappConnection | None:
        await self._representative(tenant_id, representative_id)
        self._authorized(actor_id, role, representative_id)
        connection = await self._connections.get_for_representative(tenant_id, representative_id)
        if (
            connection
            and refresh
            and connection.gateway_onboarding_id
            and connection.status is WhatsappConnectionStatus.CONNECTING
        ):
            data = await self._gateway.get_onboarding(connection.gateway_onboarding_id)
            if self._apply(connection, data):
                action = (
                    "WHATSAPP_CONNECTION_COMPLETED"
                    if connection.status is WhatsappConnectionStatus.CONNECTED
                    else "WHATSAPP_CONNECTION_ACTION_REQUIRED"
                    if connection.status is WhatsappConnectionStatus.ACTION_REQUIRED
                    else "WHATSAPP_CONNECTION_CONFLICT"
                    if connection.status is WhatsappConnectionStatus.CONFLICT
                    else "WHATSAPP_CONNECTION_FAILED"
                )
                self._audit_event(connection, actor_id, action, request_id)
        return connection

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        role: UserRole,
        representative_id: uuid.UUID,
        tenant_reference: str,
        request_id: str | None = None,
    ) -> tuple[RepresentativeWhatsappConnection, str]:
        representative = await self._representative(tenant_id, representative_id)
        self._authorized(actor_id, role, representative_id)
        existing = await self._connections.get_for_representative(tenant_id, representative_id)
        if existing and self._connections.active(existing.status):
            if (
                existing.status is WhatsappConnectionStatus.CONNECTING
                and existing.gateway_onboarding_id
            ):
                data = await self._gateway.get_onboarding(existing.gateway_onboarding_id)
                self._apply(existing, data)
                if data.launch_url:
                    return existing, data.launch_url
            raise ConnectionConflict
        connection = RepresentativeWhatsappConnection(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            representative_user_id=representative_id,
            created_by_user_id=actor_id,
            idempotency_key=uuid.uuid4().hex,
        )
        self._connections.add(connection)
        data = await self._gateway.create_onboarding(
            customer_reference=tenant_reference,
            representative_reference=representative.public_ref,
            idempotency_key=connection.idempotency_key,
        )
        connection.gateway_onboarding_id = data.onboarding_id
        self._apply(connection, data)
        self._audit_event(connection, actor_id, "WHATSAPP_CONNECTION_STARTED", request_id)
        return connection, data.launch_url or ""

    async def resume(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        role: UserRole,
        representative_id: uuid.UUID,
        request_id: str | None = None,
    ) -> tuple[RepresentativeWhatsappConnection, str]:
        connection = await self.get(
            tenant_id=tenant_id,
            actor_id=actor_id,
            role=role,
            representative_id=representative_id,
            refresh=False,
        )
        if (
            connection is None
            or not connection.gateway_onboarding_id
            or connection.status
            not in {WhatsappConnectionStatus.ACTION_REQUIRED, WhatsappConnectionStatus.FAILED}
        ):
            raise ConnectionConflict
        data = await self._gateway.resume_onboarding(
            connection.gateway_onboarding_id, idempotency_key=connection.idempotency_key
        )
        self._apply(connection, data)
        self._audit_event(connection, actor_id, "WHATSAPP_CONNECTION_RESUMED", request_id)
        return connection, data.launch_url or ""
