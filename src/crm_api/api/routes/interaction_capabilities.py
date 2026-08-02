from typing import Annotated

from fastapi import APIRouter, Depends

from crm_api.api.security import verify_internal_request
from crm_api.schemas.interaction_capabilities import InteractionCapabilitiesResponse
from crm_api.services.interaction_capabilities import get_interaction_capabilities

router = APIRouter(tags=["Interaction Capabilities"])


@router.get(
    "/internal/interaction-capabilities",
    response_model=InteractionCapabilitiesResponse,
    responses={401: {"description": "Unauthorized"}},
)
async def get_internal_interaction_capabilities(
    _: Annotated[str, Depends(verify_internal_request)],
) -> InteractionCapabilitiesResponse:
    return get_interaction_capabilities()
