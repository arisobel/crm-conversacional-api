"""Contrato `portfolio-v1` da decisão de atendimento por carteira.

O Gateway pergunta, mensagem a mensagem, se a linha de um representante pode
acionar o robô para um telefone. A regra inteira vive aqui; o Gateway só envia a
linha e o telefone e obedece. Em `DENY` a resposta não carrega dado de cliente
nenhum — o motivo basta para o log técnico do outro lado.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "portfolio-v1"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class DecisionReason(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    LINE_UNKNOWN = "LINE_UNKNOWN"
    LINE_OWNER_INACTIVE = "LINE_OWNER_INACTIVE"
    CONTACT_NOT_FOUND = "CONTACT_NOT_FOUND"
    CUSTOMER_INACTIVE = "CUSTOMER_INACTIVE"
    CUSTOMER_WITHOUT_OWNER = "CUSTOMER_WITHOUT_OWNER"
    OWNER_MISMATCH = "OWNER_MISMATCH"
    AMBIGUOUS_PHONE = "AMBIGUOUS_PHONE"
    INTERNAL_USER = "INTERNAL_USER"


class AuthorizationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_line_reference: str = Field(min_length=1, max_length=64)
    # Telefone malformado não é erro de contrato: é um remetente que o CRM não
    # conhece. Validar aqui devolveria 422, e o Gateway perderia o motivo.
    phone_e164: str = Field(min_length=1, max_length=32)
    application_slug: str = Field(min_length=1, max_length=100)
    flow_slug: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=255)


class AuthorizationDecisionResponse(BaseModel):
    decision: Decision
    reason: DecisionReason
    customer_public_ref: str | None = None
    contact_public_ref: str | None = None
    policy_version: Literal["portfolio-v1"] = POLICY_VERSION
