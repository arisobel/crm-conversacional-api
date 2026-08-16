"""Administração de usuários do portal, incluindo representantes."""

import uuid
from datetime import UTC, datetime

from crm_api.core.config import Settings
from crm_api.core.passwords import hash_password, validate_password_policy
from crm_api.core.phone import normalize_whatsapp_e164
from crm_api.models.user import User, UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.users import SessionRepository, UserRepository
from crm_api.services.auth import normalize_email


class UserNotFound(Exception):
    """Usuário inexistente no tenant da implantação."""


class EmailAlreadyUsed(Exception):
    """Já existe um usuário com este e-mail no tenant."""


class WhatsappAlreadyUsed(Exception):
    """O telefone já pertence a outro usuário ou a um contato de cliente.

    A colisão entre as duas tabelas é recusada aqui porque é a rota de escalação
    mais barata do desenho: um telefone que fosse contato de cliente e usuário
    do portal receberia capacidades de representante por um cadastro
    descuidado.
    """


class UnsafeUserChange(Exception):
    """Alteração que trancaria o portal ou o próprio autor para fora."""


class UserService:
    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        audit: AuditRepository,
        settings: Settings,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._audit = audit
        self._settings = settings

    def _check_password(self, password: str, *, email: str) -> str:
        """Valida a política e devolve o hash. Propaga `WeakPassword`."""
        validate_password_policy(
            password, email=email, min_length=self._settings.password_min_length
        )
        return hash_password(password)

    async def _get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
        user = await self._users.get_in_tenant(tenant_id, user_id)
        if user is None:
            raise UserNotFound
        return user

    async def _canonical_whatsapp(
        self,
        tenant_id: uuid.UUID,
        raw: str,
        *,
        excluding: uuid.UUID | None = None,
    ) -> str:
        """Canoniza e recusa colisão, dentro de `users` e contra os contatos.

        Propaga `InvalidWhatsappNumber` quando o número não é E.164; a rota
        traduz para `422`, como já faz no cadastro de contato.
        """
        phone = normalize_whatsapp_e164(raw)
        if await self._users.whatsapp_exists(tenant_id, phone, excluding=excluding):
            raise WhatsappAlreadyUsed("phone already belongs to another portal user")
        if await self._users.whatsapp_belongs_to_contact(tenant_id, phone):
            raise WhatsappAlreadyUsed("phone already belongs to a customer contact")
        return phone

    async def _guard_last_admin(self, user: User) -> None:
        if user.role is not UserRole.ADMIN or not user.active:
            return
        if await self._users.count_other_active_admins(user.tenant_id, user.id) == 0:
            raise UnsafeUserChange("the last active ADMIN cannot be demoted or deactivated")

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        full_name: str,
        email: str,
        password: str,
        role: UserRole,
        whatsapp_e164: str | None = None,
        request_id: str | None = None,
    ) -> User:
        normalized_email = normalize_email(email)
        if await self._users.exists_email(tenant_id, normalized_email):
            raise EmailAlreadyUsed

        password_hash = self._check_password(password, email=normalized_email)
        phone = (
            await self._canonical_whatsapp(tenant_id, whatsapp_e164) if whatsapp_e164 else None
        )
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            full_name=full_name,
            email=normalized_email,
            password_hash=password_hash,
            role=role,
            whatsapp_e164=phone,
        )
        self._users.add(user)
        self._audit.record(
            action="USER_CREATED",
            entity="users",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=user.id,
            after={"email": normalized_email, "role": role.value, "full_name": full_name},
            request_id=request_id,
        )
        return user

    async def list_users(
        self,
        *,
        tenant_id: uuid.UUID,
        role: UserRole | None = None,
        active: bool | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        total = await self._users.count_users(tenant_id, role=role, active=active)
        rows = await self._users.list_users(
            tenant_id, role=role, active=active, limit=limit, offset=offset
        )
        return rows, total

    async def get(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
        return await self._get(tenant_id, user_id)

    async def update(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        user_id: uuid.UUID,
        full_name: str | None = None,
        whatsapp_e164: str | None = None,
        role: UserRole | None = None,
        request_id: str | None = None,
    ) -> User:
        user = await self._get(tenant_id, user_id)
        before = {
            "full_name": user.full_name,
            "whatsapp_e164": user.whatsapp_e164,
            "role": user.role.value,
        }

        if role is not None and role is not user.role:
            await self._guard_last_admin(user)
            user.role = role
        if full_name is not None:
            user.full_name = full_name
        if whatsapp_e164 is not None:
            user.whatsapp_e164 = (
                await self._canonical_whatsapp(tenant_id, whatsapp_e164, excluding=user.id)
                if whatsapp_e164
                else None
            )
        user.updated_at = datetime.now(UTC)

        self._audit.record(
            action="USER_UPDATED",
            entity="users",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=user.id,
            before=before,
            after={
                "full_name": user.full_name,
                "whatsapp_e164": user.whatsapp_e164,
                "role": user.role.value,
            },
            request_id=request_id,
        )
        return user

    async def set_active(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        user_id: uuid.UUID,
        active: bool,
        request_id: str | None = None,
    ) -> User:
        user = await self._get(tenant_id, user_id)
        if not active and user.id == actor_user_id:
            raise UnsafeUserChange("a user cannot deactivate their own account")
        if not active:
            await self._guard_last_admin(user)

        was_active = user.active
        user.active = active
        user.updated_at = datetime.now(UTC)
        revoked = 0
        if not active:
            # Sem isso, um cookie já emitido continuaria valendo até expirar.
            revoked = await self._sessions.revoke_all_for_user(user.id, now=datetime.now(UTC))
            user.failed_login_attempts = 0
            user.locked_until = None

        self._audit.record(
            action="USER_ACTIVATED" if active else "USER_DEACTIVATED",
            entity="users",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=user.id,
            before={"active": was_active},
            after={"active": active, "revoked_sessions": revoked},
            request_id=request_id,
        )
        return user

    async def set_password(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        user_id: uuid.UUID,
        password: str,
        request_id: str | None = None,
    ) -> User:
        """Define uma senha para outro usuário.

        Revoga todas as sessões dele: se a troca foi feita porque a conta pode
        ter sido comprometida, manter a sessão antiga viva anularia a medida.
        """
        user = await self._get(tenant_id, user_id)
        user.password_hash = self._check_password(password, email=user.email)
        user.failed_login_attempts = 0
        user.locked_until = None
        user.updated_at = datetime.now(UTC)
        revoked = await self._sessions.revoke_all_for_user(user.id, now=datetime.now(UTC))

        self._audit.record(
            action="USER_PASSWORD_RESET",
            entity="users",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=user.id,
            after={"revoked_sessions": revoked},
            request_id=request_id,
        )
        return user
