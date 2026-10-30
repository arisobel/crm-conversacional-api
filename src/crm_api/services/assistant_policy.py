"""Decisão comercial da linha assistente, sem alterar autorização existente.

Primeiro corte: regras puras para composição e validação. A origem persistente,
o manifesto e os executores ainda não consomem esta política.
"""

from dataclasses import dataclass


REPRESENTATIVE_CAPABILITIES = frozenset({
    "CRM_REP_SEARCH_PRICE_ITEMS",
    "CRM_REP_LOOKUP_CUSTOMER",
    "CRM_REP_GET_CUSTOMER_PRICE_LIST",
    "CRM_REP_GET_CUSTOMER_CONVERSATION_SUMMARY",
    "CRM_REP_CREATE_CUSTOMER_INTAKE",
})


@dataclass(frozen=True)
class AssistantPolicy:
    organization_enabled: bool = False
    representative_enabled: bool = False
    enabled_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        unknown = self.enabled_capabilities - REPRESENTATIVE_CAPABILITIES
        if unknown:
            raise ValueError("unknown or non-representative assistant capability")

    def effective_capabilities(self) -> frozenset[str]:
        if not self.organization_enabled or not self.representative_enabled:
            return frozenset()
        return self.enabled_capabilities

    def allows(self, capability: str) -> bool:
        return capability in self.effective_capabilities()
