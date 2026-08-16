"""Ingestão do histórico de interações e leitura da timeline.

Duas portas com esquemas de autenticação distintos e sem interseção: a ingestão
aceita apenas o HMAC do Gateway; a timeline, apenas a sessão do portal.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.authentication import CurrentUser, get_current_user
from crm_api.api.scoping import scope_for
from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.models.user import UserRole
from crm_api.repositories.audit import AuditRepository
from crm_api.repositories.interactions import InteractionRepository
from crm_api.repositories.portfolio import CustomerPortfolioRepository
from crm_api.repositories.users import UserRepository
from crm_api.schemas.interactions import (
    IngestInteractionsRequest,
    IngestInteractionsResponse,
    IngestOutcomeResponse,
    InteractionPage,
    InteractionResponse,
)
from crm_api.services.interactions import IncomingInteraction, InteractionService
from crm_api.services.portfolio import CustomerNotInScope

router = APIRouter(tags=["Interactions"])


def _service(session: AsyncSession) -> InteractionService:
    return InteractionService(
        session=session,
        interactions=InteractionRepository(session),
        portfolio=CustomerPortfolioRepository(session),
        audit=AuditRepository(session),
    )


@router.post(
    "/internal/interactions",
    response_model=IngestInteractionsResponse,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Tenant not found"},
    },
)
async def ingest_interactions(
    payload: IngestInteractionsRequest,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestInteractionsResponse:
    """Recebe eventos do Gateway e os projeta na ficha do cliente.

    Responde `200` mesmo com itens recusados, com o desfecho de cada um. Um
    evento não resolvido é problema daquele evento: derrubar o lote inteiro
    faria o Gateway reenviar indefinidamente os que já tinham sido aceitos.
    """
    tenant = await UserRepository(session).get_tenant(tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    relatorio = await _service(session).ingest(
        tenant_id=tenant.id,
        eventos=[
            IncomingInteraction(
                external_ref=item.external_ref,
                direction=item.direction,
                occurred_at=item.occurred_at,
                whatsapp_e164=item.whatsapp_e164,
                customer_id=item.customer_id,
                source=item.source,
                channel=item.channel,
                summary=item.summary,
                payload=item.payload,
            )
            for item in payload.interactions
        ],
    )
    await session.commit()

    return IngestInteractionsResponse(
        created=relatorio.created,
        duplicated=relatorio.duplicated,
        rejected=relatorio.rejected,
        results=[
            IngestOutcomeResponse(
                external_ref=resultado.external_ref,
                outcome=resultado.outcome.value,
                interaction_id=resultado.interaction_id,
                reason=resultado.reason,
            )
            for resultado in relatorio.results
        ],
    )


@router.get(
    "/admin/customers/{customer_id}/interactions",
    response_model=InteractionPage,
    responses={404: {"description": "Customer not found or outside the portfolio"}},
)
async def customer_timeline(
    customer_id: uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InteractionPage:
    try:
        interacoes, total = await _service(session).timeline(
            scope_for(current_user), customer_id, limit=limit, offset=offset
        )
    except CustomerNotInScope as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="customer not found"
        ) from error

    return _page(interacoes, total=total, limit=limit, offset=offset)


@router.get(
    "/admin/users/{user_id}/interactions",
    response_model=InteractionPage,
    responses={
        403: {"description": "Reading someone else's conversation requires ADMIN"},
        404: {"description": "User not found"},
    },
)
async def user_timeline(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InteractionPage:
    """Conversa de um usuário do portal pelo WhatsApp.

    Cada um lê a sua; ler a de outro exige `ADMIN`. Não é escopo de carteira —
    é conteúdo de conversa de uma pessoa identificada, e o `MANAGER` que
    administra carteiras não tem motivo para lê-la.
    """
    if user_id != current_user.user_id and current_user.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role"
        )
    if await UserRepository(session).get_in_tenant(current_user.tenant_id, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    interacoes, total = await _service(session).actor_timeline(
        current_user.tenant_id, user_id, limit=limit, offset=offset
    )
    return _page(interacoes, total=total, limit=limit, offset=offset)


def _page(interacoes, *, total: int, limit: int, offset: int) -> InteractionPage:
    return InteractionPage(
        items=[
            InteractionResponse(
                interaction_id=interacao.id,
                customer_id=interacao.customer_id,
                actor_user_id=interacao.actor_user_id,
                contact_id=interacao.contact_id,
                channel=interacao.channel,
                direction=interacao.direction,
                source=interacao.source,
                external_ref=interacao.external_ref,
                occurred_at=interacao.occurred_at,
                summary=interacao.summary,
            )
            for interacao in interacoes
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
