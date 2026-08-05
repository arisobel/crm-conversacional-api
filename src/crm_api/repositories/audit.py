import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.user import AuditLog


class AuditRepository:
    """Escrita da trilha de auditoria.

    Só existe `record`. A trilha é append-only por decisão de produto: não há
    aqui update nem delete, e a leitura pertence às telas de auditoria (R6).
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    def record(
        self,
        *,
        action: str,
        entity: str,
        tenant_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        before: dict | None = None,
        after: dict | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            before=before,
            after=after,
            request_id=request_id,
        )
        self._session.add(entry)
        return entry
