"""Autenticação do portal do representante.

Separada do HMAC do Gateway por decisão explícita (R0): uma chamada assinada
entre serviços nunca concede papel administrativo, e uma sessão de portal nunca
autoriza as rotas internas do Gateway.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from crm_api.core.config import Settings
from crm_api.core.passwords import dummy_hash, hash_password, needs_rehash, verify_password
from crm_api.models.user import User, UserSession
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.users import SessionRepository, UserRepository

_TOKEN_BYTES = 32


class AuthenticationFailed(Exception):
    """Credencial inválida, conta inativa ou conta bloqueada.

    Um único tipo para os três casos: distinguí-los na resposta transformaria o
    login em um oráculo de existência de conta.
    """


class LoginRateLimited(Exception):
    """Excesso de tentativas na janela; a requisição sequer chega ao banco."""


@dataclass(frozen=True)
class IssuedSession:
    token: str
    expires_at: datetime
    user: User


def normalize_email(value: str) -> str:
    return value.strip().lower()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Normaliza datas lidas do banco.

    O PostgreSQL devolve `timestamptz` com fuso; o SQLite usado nos testes
    descarta o offset e devolve naive. Sem esta normalização, qualquer aritmética
    entre os dois quebra em tempo de execução apenas em um dos ambientes.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AuthService:
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

    async def authenticate(
        self,
        *,
        tenant_slug: str,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> IssuedSession:
        now = datetime.now(UTC)
        normalized_email = normalize_email(email)
        user = await self._users.get_by_email(tenant_slug, normalized_email)

        if user is None:
            # Verificação descartada apenas para consumir o mesmo tempo de um
            # login com usuário existente.
            verify_password(dummy_hash(), password)
            self._audit.record(
                action="LOGIN_FAILED",
                entity="users",
                after={"email": normalized_email, "reason": "UNKNOWN_EMAIL"},
                request_id=request_id,
            )
            raise AuthenticationFailed

        locked = user.locked_until is not None and _as_utc(user.locked_until) > now
        password_matches = verify_password(user.password_hash, password)

        if locked:
            self._audit.record(
                action="LOGIN_BLOCKED",
                entity="users",
                tenant_id=user.tenant_id,
                actor_user_id=user.id,
                entity_id=user.id,
                after={"reason": "ACCOUNT_LOCKED"},
                request_id=request_id,
            )
            raise AuthenticationFailed

        if not password_matches or not user.active:
            reason = "INVALID_CREDENTIALS" if not password_matches else "INACTIVE_USER"
            if not password_matches:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= self._settings.login_max_failed_attempts:
                    user.locked_until = now + timedelta(
                        seconds=self._settings.login_lockout_seconds
                    )
            self._audit.record(
                action="LOGIN_FAILED",
                entity="users",
                tenant_id=user.tenant_id,
                actor_user_id=user.id,
                entity_id=user.id,
                after={"reason": reason, "failed_attempts": user.failed_login_attempts},
                request_id=request_id,
            )
            raise AuthenticationFailed

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires_at = now + timedelta(seconds=self._settings.session_ttl_seconds)
        absolute_expires_at = now + timedelta(
            seconds=max(
                self._settings.session_absolute_ttl_seconds,
                self._settings.session_ttl_seconds,
            )
        )
        self._sessions.add(
            UserSession(
                id=uuid.uuid4(),
                tenant_id=user.tenant_id,
                user_id=user.id,
                token_hash=hash_session_token(token),
                last_seen_at=now,
                expires_at=expires_at,
                absolute_expires_at=absolute_expires_at,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        self._audit.record(
            action="LOGIN_SUCCEEDED",
            entity="users",
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            entity_id=user.id,
            after={"ip_address": ip_address},
            request_id=request_id,
        )
        return IssuedSession(token=token, expires_at=expires_at, user=user)

    async def resolve(self, token: str) -> tuple[UserSession, User] | None:
        """Resolve o cookie em sessão e usuário, ou devolve `None`.

        Revalida `user.active` a cada requisição e revoga a sessão quando o
        usuário foi desativado — é o que faz a desativação ter efeito imediato
        sobre cookies já emitidos.
        """
        if not token:
            return None

        now = datetime.now(UTC)
        found = await self._sessions.get_active_by_token_hash(hash_session_token(token), now=now)
        if found is None:
            return None

        user_session, user = found
        if not user.active:
            await self._sessions.revoke(user_session.id, now=now)
            return None

        await self._renew_if_needed(user_session, now=now)
        return user_session, user

    async def _renew_if_needed(self, user_session: UserSession, *, now: datetime) -> None:
        """Estende a janela deslizante, sem gravar a cada requisição."""
        ttl = timedelta(seconds=self._settings.session_ttl_seconds)
        expires_at = _as_utc(user_session.expires_at)
        if expires_at - now > ttl / 2:
            return

        absolute_expires_at = _as_utc(user_session.absolute_expires_at)
        renewed = min(now + ttl, absolute_expires_at)
        await self._sessions.touch(user_session.id, now=now, expires_at=renewed)
        user_session.expires_at = renewed
        user_session.last_seen_at = now

    async def logout(
        self,
        *,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        request_id: str | None = None,
    ) -> None:
        await self._sessions.revoke(session_id, now=datetime.now(UTC))
        self._audit.record(
            action="LOGOUT",
            entity="user_sessions",
            tenant_id=tenant_id,
            actor_user_id=user_id,
            entity_id=session_id,
            request_id=request_id,
        )

    async def deactivate_sessions(self, user_id: uuid.UUID) -> int:
        return await self._sessions.revoke_all_for_user(user_id, now=datetime.now(UTC))
