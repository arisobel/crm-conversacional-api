from crm_api.schemas.interaction_capabilities import (
    InteractionCapabilitiesResponse,
    InteractionIntentResponse,
)

_SESSION_TTL_SECONDS = 30 * 60


def get_interaction_capabilities() -> InteractionCapabilitiesResponse:
    return InteractionCapabilitiesResponse(
        provider="crm_api",
        version="1",
        session_ttl_seconds=_SESSION_TTL_SECONDS,
        fallback_message=(
            "Posso enviar a tabela atual ou consultar um artigo. "
            "Exemplos: ‘lista de preços’ ou ‘75/36 urdume’."
        ),
        intents=[
            InteractionIntentResponse(
                id="LIST_CURRENT_PRICES",
                description="Envia a tabela de preços vigente para o contato.",
                aliases=[
                    "tabela",
                    "lista",
                    "listagem",
                    "lista de preços",
                    "tabela de valores",
                    "lista de valores",
                    "matriz de preços",
                    "guia de preços",
                    "estrutura de preços",
                    "relação de produtos e preços",
                    "valores atuais",
                    "preços atuais",
                ],
                examples=[
                    "poderia me fornecer a lista de preços atual?",
                    "me envie a tabela de valores",
                ],
                action="GET_CURRENT_PRICE_LIST",
            ),
            InteractionIntentResponse(
                id="SEARCH_PRODUCT",
                description=(
                    "Consulta produto, preço-base, disponibilidade ou previsão de chegada "
                    "na tabela vigente."
                ),
                examples=[
                    "75/36",
                    "tem 75/36 urdume?",
                    "preço do PUE 20",
                    "quando chega o 100/36?",
                ],
                action="SEARCH_CURRENT_PRICE_LIST_ITEMS",
                required_slots=["product_query"],
            ),
        ],
    )
