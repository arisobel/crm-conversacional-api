from crm_api.schemas.assistant_conversation import (
    AssistantAllowedAction,
    AssistantConversationDirective,
    AssistantOperation,
    AssistantOutcomeState,
)


def test_directive_serializes_as_stable_gateway_contract():
    directive = AssistantConversationDirective(
        operation=AssistantOperation.PRICE_UPDATE,
        state=AssistantOutcomeState.WAITING_CONFIRMATION,
        requires_confirmation=True,
        allowed_actions=[AssistantAllowedAction.CONFIRM, AssistantAllowedAction.CANCEL],
    )

    assert directive.model_dump(mode="json") == {
        "operation": "PRICE_UPDATE",
        "state": "WAITING_CONFIRMATION",
        "requires_confirmation": True,
        "missing_fields": [],
        "allowed_actions": ["CONFIRM", "CANCEL"],
    }


def test_directive_keeps_missing_data_structured_instead_of_prescribing_phrase():
    directive = AssistantConversationDirective(
        operation=AssistantOperation.PRICE_UPDATE,
        state=AssistantOutcomeState.NEEDS_INPUT,
        missing_fields=["duplicate_skus", "incomplete_rows"],
        allowed_actions=[AssistantAllowedAction.RESUBMIT, AssistantAllowedAction.CANCEL],
    )

    payload = directive.model_dump(mode="json")

    assert payload["missing_fields"] == ["duplicate_skus", "incomplete_rows"]
    assert "message" not in payload
    assert "reply" not in payload
