import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer import Tenant
from crm_api.models.user import User, UserSession


class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_tenant(self, tenant_slug: str) -> Tenant | None:
        return await self._session.scalar(
            select(Tenant).where(Tenant.slug == tenant_slug, Tenant.active.is_(True))
        )

    async def get_by_email(self, tenant_slug: str, email: str) -> User | None:
        """Busca por e-mail já normalizado, restrita ao tenant da implantação.

        Inclui usuários inativos de propósito: quem decide o que responder é o
        serviço de autenticação, que precisa tratar ativo e inativo com a mesma
        resposta e o mesmo custo.
        """
        return await self._session.scalar(
            select(User)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(Tenant.slug == tenant_slug, Tenant.active.is_(True), User.email == email)
        )

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.scalar(select(User).where(User.id == user_id))

    def add(self, user: User) -> None:
        self._session.add(user)


class SessionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def add(self, user_session: UserSession) -> None:
        self._session.add(user_session)

    async def get_active_by_token_hash(
        self, token_hash: str, *, now: datetime
    ) -> tuple[UserSession, User] | None:
        result = await self._session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
                UserSession.absolute_expires_at > now,
            )
        )
        return result.one_or_none()

    async def revoke(self, session_id: uuid.UUID, *, now: datetime) -> None:
        await self._session.execute(
            update(UserSession)
            .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID, *, now: datetime) -> int:
        """Revoga todas as sessões vigentes de um usuário.

        Chamado ao desativar o usuário: sem isso, um cookie já emitido
        continuaria valendo até expirar.
        """
        result = await self._session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return result.rowcount or 0

    async def touch(
        self, session_id: uuid.UUID, *, now: datetime, expires_at: datetime
    ) -> None:
        await self._session.execute(
            update(UserSession)
            .where(UserSession.id == session_id)
            .values(last_seen_at=now, expires_at=expires_at)
        )
