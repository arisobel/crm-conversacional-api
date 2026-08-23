from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from crm_api.models.interaction import (
    GATEWAY_SOURCE,
    WHATSAPP_CHANNEL,
    InteractionDirection,
    InteractionKind,
)

_LOTE_MAXIMO = 200


class IncomingInteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_ref: str = Field(
        min_length=1,
        max_length=200,
        description="Identificador do evento na origem. Reenviar o mesmo não duplica.",
    )
    direction: InteractionDirection
    occurred_at: datetime
    whatsapp_e164: str | None = Field(
        default=None,
        description="Telefone do contato. Alternativa a `customer_id`; um dos dois é exigido.",
    )
    customer_id: UUID | None = None
    source: str = Field(default=GATEWAY_SOURCE, min_length=1, max_length=60)
    channel: str = Field(default=WHATSAPP_CHANNEL, min_length=1, max_length=40)
    summary: str | None = Field(
        default=None,
        description="Texto ou resumo da mensagem. Truncado em 2000 caracteres.",
    )
    payload: dict | None = None


class IngestInteractionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interactions: list[IncomingInteractionRequest] = Field(
        min_length=1, max_length=_LOTE_MAXIMO
    )


class IngestOutcomeResponse(BaseModel):
    external_ref: str
    outcome: str = Field(description="CREATED, DUPLICATE ou REJECTED.")
    interaction_id: UUID | None = None
    reason: str | None = None


class IngestInteractionsResponse(BaseModel):
    created: int
    duplicated: int
    rejected: int
    results: list[IngestOutcomeResponse]


class InteractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    interaction_id: UUID
    kind: InteractionKind = Field(
        description=(
            "Qual das três formas: conversa do cliente com o robô, do "
            "representante com o robô, ou nota registrada à mão na ficha."
        )
    )
    # Quais vêm preenchidos depende de `kind`, e o banco garante a combinação:
    # canal de cliente tem só `customer_id`, canal de ator tem só
    # `actor_user_id`, e a nota manual tem os dois.
    customer_id: UUID | None
    actor_user_id: UUID | None = None
    contact_id: UUID | None
    channel: str
    # Nulo só em nota: uma ligação é feita ou recebida, mas uma visita não é
    # nem uma nem outra.
    direction: InteractionDirection | None
    source: str
    external_ref: str
    occurred_at: datetime
    summary: str | None
    edited_at: datetime | None = Field(
        default=None,
        description="Preenchido quando a nota foi corrigida. Sempre nulo em evento de canal.",
    )


class InteractionPage(BaseModel):
    items: list[InteractionResponse]
    total: int
    limit: int
    offset: int
