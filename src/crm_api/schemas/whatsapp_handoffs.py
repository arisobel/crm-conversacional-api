"""Contrato privado do lembrete de atendimento humano."""

from pydantic import BaseModel, ConfigDict, Field


class HandoffReminderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_line_reference: str = Field(min_length=1, max_length=64)
    customer_phone_e164: str = Field(min_length=1, max_length=32)


class HandoffReminderResponse(BaseModel):
    decision: str
    representative_phone_e164: str | None = None
    representative_name: str | None = None
    customer_name: str | None = None
