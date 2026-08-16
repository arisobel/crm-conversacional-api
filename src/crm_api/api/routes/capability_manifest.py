"""Endpoint canônico de capacidades, resolvido por contato.

O `GET /internal/interaction-capabilities` continua servindo o manifesto antigo,
intocado, até o Gateway virar a flag dele (ADR-022). Enquanto os dois existirem,
este é o único que sabe quem está falando.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from crm_api.api.security import verify_internal_request
from crm_api.core.database import get_session
from crm_api.core.phone import InvalidWhatsappNumber, normalize_whatsapp_e164
from crm_api.repositories.users import UserRepository
from crm_api.schemas.capability_manifest import CapabilityManifest, ManifestRequest
from crm_api.services.capability_manifest import build_manifest
from crm_api.services.whatsapp_actor import (
    ActorNotFound,
    AmbiguousActor,
    WhatsappActorResolver,
)

router = APIRouter(tags=["Capability Manifest"])


@router.post(
    "/api/integrations/whatsapp/v1/capabilities/manifest",
    response_model=CapabilityManifest,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Tenant unknown, or no actor matches this phone"},
        409: {"description": "Phone belongs to both a portal user and a customer contact"},
        422: {"description": "Phone is not a valid E.164 number"},
    },
)
async def capabilities_manifest(
    payload: ManifestRequest,
    tenant_slug: Annotated[str, Depends(verify_internal_request)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CapabilityManifest:
    """Devolve o que **este contato** pode fazer, e nada além disso.

    A diferença entre representante e cliente vive aqui, não no roteamento: o
    Gateway encaminha os dois pelo mesmo fluxo, e um telefone ativo em dois
    fluxos da mesma linha faria a mensagem ser descartada em silêncio.
    """
    tenant = await UserRepository(session).get_tenant(tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    try:
        telefone = normalize_whatsapp_e164(payload.contact_phone_e164)
    except InvalidWhatsappNumber as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    try:
        actor = await WhatsappActorResolver(session).resolve(tenant.id, telefone)
    except AmbiguousActor as error:
        # Falha fechada: o Gateway cai no fallback dele e ninguém recebe alçada
        # por causa de um cadastro descuidado.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ActorNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error

    return build_manifest(actor, payload.channel_context)
