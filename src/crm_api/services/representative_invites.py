"""Convites autocadastráveis para representantes do portal."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from crm_api.models.user import RepresentativeInvite, RepresentativeInviteStatus, User
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.representative_invites import RepresentativeInviteRepository

INVITE_TTL = timedelta(days=7)
_TOKEN_BYTES = 32


class RepresentativeInviteUnavailable(Exception):
    """Convite inexistente, utilizado, revogado ou vencido."""

    def __init__(self, invite: RepresentativeInvite | None = None) -> None:
        super().__init__("representative invite unavailable")
        self.invite = invite


@dataclass(frozen=True)
class IssuedRepresentativeInvite:
    invite: RepresentativeInvite
    token: str


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class RepresentativeInviteService:
    def __init__(
        self,
        *,
        invites: RepresentativeInviteRepository,
        audit: AuditRepository,
    ) -> None:
        self._invites = invites
        self._audit = audit

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        request_id: str | None = None,
    ) -> IssuedRepresentativeInvite:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        invite = RepresentativeInvite(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            token_hash=hash_invite_token(token),
            status=RepresentativeInviteStatus.PENDING,
            created_by_user_id=actor_user_id,
            expires_at=now + INVITE_TTL,
            updated_at=now,
        )
        self._invites.add(invite)
        self._audit.record(
            action="REPRESENTATIVE_INVITE_CREATED",
            entity="representative_invites",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_id=invite.id,
            after={"expires_at": invite.expires_at.isoformat()},
            request_id=request_id,
        )
        return IssuedRepresentativeInvite(invite=invite, token=token)

    async def resolve(
        self, token: str, *, for_update: bool = False
    ) -> RepresentativeInvite:
        invite = await self._invites.get_by_token_hash(
            hash_invite_token(token), for_update=for_update
        )
        if invite is None or invite.status is not RepresentativeInviteStatus.PENDING:
            raise RepresentativeInviteUnavailable(invite)
        now = datetime.now(UTC)
        if _as_utc(invite.expires_at) <= now:
            invite.status = RepresentativeInviteStatus.EXPIRED
            invite.updated_at = now
            raise RepresentativeInviteUnavailable(invite)
        return invite

    def accept(
        self,
        invite: RepresentativeInvite,
        user: User,
        *,
        request_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        invite.status = RepresentativeInviteStatus.ACCEPTED
        invite.representative_user_id = user.id
        invite.accepted_at = now
        invite.updated_at = now
        self._audit.record(
            action="REPRESENTATIVE_INVITE_ACCEPTED",
            entity="representative_invites",
            tenant_id=invite.tenant_id,
            actor_user_id=user.id,
            entity_id=invite.id,
            after={"representative_user_id": str(user.id)},
            request_id=request_id,
        )
