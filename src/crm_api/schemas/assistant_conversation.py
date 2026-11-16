"""Diretiva segura para a resposta conversacional do Gateway.

O CRM decide estado e acoes permitidas; o Gateway pode redigir a mensagem em
linguagem natural sem transformar texto gerado em fonte de verdade ou comando.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class AssistantOperation(StrEnum):
    CUSTOMER_INTAKE = "CUSTOMER_INTAKE"
    REMINDER = "REMINDER"
    PRICE_UPDATE = "PRICE_UPDATE"


class AssistantOutcomeState(StrEnum):
    IDLE = "IDLE"
    ATTACHED = "ATTACHED"
    NEEDS_INPUT = "NEEDS_INPUT"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_REVIEW = "WAITING_REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssistantAllowedAction(StrEnum):
    REVIEW_IN_CRM = "REVIEW_IN_CRM"
    CANCEL = "CANCEL"
    RESCHEDULE = "RESCHEDULE"
    CONFIRM = "CONFIRM"
    RESUBMIT = "RESUBMIT"
    ANALYZE_PRICE_UPDATE = "ANALYZE_PRICE_UPDATE"
    ARCHIVE_IN_CRM = "ARCHIVE_IN_CRM"


class AssistantConversationDirective(BaseModel):
    """Limites para o redator natural do Gateway.

    `missing_fields` usa nomes do contrato, nao frases prontas. Dessa forma o
    Gateway pode perguntar naturalmente, mas somente sobre informacoes que o
    dominio realmente declarou como ausentes.
    """

    operation: AssistantOperation
    state: AssistantOutcomeState
    requires_confirmation: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    allowed_actions: list[AssistantAllowedAction] = Field(default_factory=list)
