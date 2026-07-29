from pydantic import BaseModel, Field


class InteractionIntentResponse(BaseModel):
    id: str
    description: str
    aliases: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    action: str
    required_slots: list[str] = Field(default_factory=list)


class InteractionCapabilitiesResponse(BaseModel):
    provider: str
    version: str
    session_ttl_seconds: int = Field(ge=60, le=86_400)
    fallback_message: str
    intents: list[InteractionIntentResponse]
