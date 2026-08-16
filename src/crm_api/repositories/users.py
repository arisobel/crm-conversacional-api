import uuid
from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.models.customer import Tenant
from crm_api.models.customer_contact import CustomerContact
from crm_api.models.user import User, UserRole, UserSession


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

    async def get_in_tenant(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        return await self._session.scalar(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )

    async def exists_email(self, tenant_id: uuid.UUID, email: str) -> bool:
        found = await self._session.scalar(
            select(User.id).where(User.tenant_id == tenant_id, User.email == email)
        )
        return found is not None

    async def whatsapp_exists(
        self, tenant_id: uuid.UUID, phone: str, *, excluding: uuid.UUID | None = None
    ) -> bool:
        statement = select(User.id).where(
            User.tenant_id == tenant_id, User.whatsapp_e164 == phone
        )
        if excluding is not None:
            statement = statement.where(User.id != excluding)
        return await self._session.scalar(statement) is not None

    async def whatsapp_belongs_to_contact(self, tenant_id: uuid.UUID, phone: str) -> bool:
        """O mesmo telefone já é contato de cliente neste tenant?

        A invariante atravessa duas tabelas, e nenhum índice a alcança — daí a
        consulta explícita, mais o `check-whatsapp-identities` do `admin_cli`
        para provar periodicamente que ela continua valendo.
        """
        found = await self._session.scalar(
            select(CustomerContact.id).where(
                CustomerContact.tenant_id == tenant_id,
                CustomerContact.whatsapp_e164 == phone,
            )
        )
        return found is not None

    async def list_active_without_whatsapp(
        self, tenant_id: uuid.UUID
    ) -> list[tuple[str, str]]:
        """Usuários ativos sem telefone — invisíveis para a resolução de ator."""
        rows = await self._session.execute(
            select(User.full_name, User.email)
            .where(
                User.tenant_id == tenant_id,
                User.active.is_(True),
                User.whatsapp_e164.is_(None),
            )
            .order_by(User.full_name)
        )
        return [(name, email) for name, email in rows]

    async def list_whatsapp_collisions(self, tenant_id: uuid.UUID) -> list[str]:
        """Telefones que são, ao mesmo tempo, usuário e contato de cliente."""
        contacts = select(CustomerContact.whatsapp_e164).where(
            CustomerContact.tenant_id == tenant_id
        )
        rows = await self._session.scalars(
            select(User.whatsapp_e164)
            .where(
                User.tenant_id == tenant_id,
                User.whatsapp_e164.is_not(None),
                User.whatsapp_e164.in_(contacts),
            )
            .order_by(User.whatsapp_e164)
        )
        return list(rows)

    def _listing(
        self, tenant_id: uuid.UUID, *, role: UserRole | None, active: bool | None
    ) -> Select[tuple[User]]:
        statement = select(User).where(User.tenant_id == tenant_id)
        if role is not None:
            statement = statement.where(User.role == role)
        if active is not None:
            statement = statement.where(User.active.is_(active))
        return statement

    async def list_users(
        self,
        tenant_id: uuid.UUID,
        *,
        role: UserRole | None = None,
        active: bool | None = None,
        limit: int,
        offset: int,
    ) -> list[User]:
        statement = (
            self._listing(tenant_id, role=role, active=active)
            .order_by(User.full_name, User.id)
            .limit(limit)
            .offset(offset)
        )
        return list(await self._session.scalars(statement))

    async def count_users(
        self, tenant_id: uuid.UUID, *, role: UserRole | None = None, active: bool | None = None
    ) -> int:
        statement = self._listing(tenant_id, role=role, active=active).with_only_columns(
            func.count(User.id)
        )
        return await self._session.scalar(statement.order_by(None)) or 0

    async def count_other_active_admins(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """Conta administradores ativos além do informado.

        Usado para impedir que a última conta `ADMIN` seja desativada ou
        rebaixada — o que trancaria todo mundo para fora do portal sem caminho
        de recuperação pela própria aplicação.
        """
        return (
            await self._session.scalar(
                select(func.count(User.id)).where(
                    User.tenant_id == tenant_id,
                    User.role == UserRole.ADMIN,
                    User.active.is_(True),
                    User.id != user_id,
                )
            )
            or 0
        )

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
