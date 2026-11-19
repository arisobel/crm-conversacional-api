from crm_api.schemas.capability_manifest import ChannelContext
from crm_api.services.capability_manifest import build_manifest
from crm_api.services.interaction_capabilities import get_interaction_capabilities
from crm_api.services.whatsapp_actor import ActorRole, WhatsappActor


def test_customer_help_is_a_natural_opening():
    manifest = build_manifest(
        WhatsappActor(
            role=ActorRole.CUSTOMER,
            public_ref="a" * 24,
            display_name="Mariana",
        ),
        ChannelContext(),
    )

    assert manifest.help_message == (
        "Oi, Mariana, tudo bem? Como posso te ajudar? Posso enviar a tabela atual ou "
        "consultar pre\u00e7o, disponibilidade e previs\u00e3o de chegada de um produto."
    )


def test_representative_help_does_not_expose_a_technical_classification():
    manifest = build_manifest(
        WhatsappActor(
            role=ActorRole.REPRESENTATIVE,
            public_ref="b" * 24,
            display_name="Patricia",
        ),
        ChannelContext(),
    )

    assert manifest.help_message.startswith("Oi, Patricia, tudo bem?")
    assert "n\u00famero est\u00e1 cadastrado" not in manifest.help_message


def test_unintelligible_message_uses_the_requested_clarification():
    capabilities = get_interaction_capabilities()

    assert capabilities.fallback_message == (
        "Para eu te ajudar certo: voc\u00ea quer receber a tabela de pre\u00e7os ou "
        "consultar um produto?"
    )
