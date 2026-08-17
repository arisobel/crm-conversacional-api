"""Contrato do pré-cadastro aberto pelo WhatsApp.

A `idempotency_key` é obrigatória e não tem padrão. O Gateway reentrega webhook;
uma escrita sem chave seria um pré-cadastro duplicado a cada reentrega, e a
capacidade declara `idempotency: "required"` justamente porque o CRM exige.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from crm_api.models.customer_intake import IntakeStatus


class OpenCustomerIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # O `wamid` da mensagem que o representante confirmou. Vem do Gateway; o CRM
    # não o interpreta, apenas exige que seja estável para a mesma mensagem.
    idempotency_key: str = Field(min_length=8, max_length=128)
    legal_name: str = Field(min_length=2, max_length=200)
    # Obrigatória: sem UF não há regra de ICMS, e o motor do R4 falha de propósito
    # em vez de estimar. Validada contra as 27 unidades federativas no serviço.
    state_code: str = Field(min_length=2, max_length=2)
    whatsapp_e164: str | None = Field(default=None, min_length=8, max_length=20)
    # Texto do representante, **não** SKU. A resolução para artigo do catálogo é
    # decisão comercial e acontece no portal (ADR-021).
    preferred_products_text: str | None = Field(default=None, max_length=500)


class CustomerIntakeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intake_id: uuid.UUID
    status: IntakeStatus
    legal_name: str
    state_code: str
    has_whatsapp: bool
    preferred_products_text: str | None
    created_at: datetime
    # `False` quando esta mensagem já havia aberto o pré-cadastro. Quem redige a
    # resposta ao representante usa isto para não confirmar duas vezes a mesma
    # abertura.
    created: bool
