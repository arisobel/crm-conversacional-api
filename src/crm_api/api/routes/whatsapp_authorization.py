from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.schemas.whatsapp_authorization import (
    AuthorizationDecisionRequest,
    AuthorizationDecisionResponse,
)
from crm_api.services.whatsapp_authorization import PortfolioAuthorizationService

router = APIRouter(tags=["WhatsApp Authorization"])


@router.post(
    "/internal/whatsapp/authorization-decision",
    response_model=AuthorizationDecisionResponse,
    response_model_exclude_none=True,
    responses={
        401: {"description": "Unauthorized"},
        422: {"description": "Malformed request body"},
    },
)
async def authorization_decision(
    payload: AuthorizationDecisionRequest,
    request: Request,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthorizationDecisionResponse:
    """Esta linha pode acionar o robô para este telefone?

    ALLOW e DENY são ambos `200`: negar é resposta, não erro. Qualquer outra
    coisa — 401, 5xx, timeout — o Gateway trata como DENY, então a
    indisponibilidade do CRM deixa o robô mudo e não aberto.
    """
    outcome = await PortfolioAuthorizationService(session).decide(tenant_slug, payload)
    await session.commit()
    request.app.logger.info(
        "whatsapp authorization decision=%s reason=%s message_id=%s",
        outcome.decision.value,
        outcome.reason.value,
        payload.message_id,
    )
    return AuthorizationDecisionResponse(
        decision=outcome.decision,
        reason=outcome.reason,
        customer_public_ref=outcome.customer_public_ref,
        contact_public_ref=outcome.contact_public_ref,
    )
