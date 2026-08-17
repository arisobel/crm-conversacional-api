"""Montagem do manifesto de capacidades por ator.

Uma regra governa tudo aqui: **só entra capacidade cujo executor já exista no
Gateway.** A allowlist de lá recusa o manifesto inteiro por causa de uma ação
desconhecida, e um manifesto recusado deixa o contato sem resposta. Anunciar
aqui uma capacidade que ninguém sabe executar não adianta a entrega — atrasa a
de todo mundo.

Hoje os dois executores registrados, `GET_CURRENT_PRICE_LIST` e
`SEARCH_CURRENT_PRICE_LIST_ITEMS`, resolvem a tabela **pelo telefone de quem
escreveu**, procurando um cliente. Servidos a um representante, respondem que
não há tabela para o cadastro dele. Por isso o representante recebe uma lista
vazia de capacidades e uma mensagem que diz a verdade, em vez de duas
capacidades que falhariam. As capacidades dele chegam na W6, junto com os
executores correspondentes.
"""

from crm_api.schemas.capability_manifest import (
    Actor,
    Capability,
    CapabilityManifest,
    CapabilityMode,
    ChannelContext,
    Idempotency,
    Slot,
    SlotKind,
    Vocabulary,
)
from crm_api.services.whatsapp_actor import ActorRole, WhatsappActor

# Teto do Gateway é 900. O cliente fica nele; o representante recebe menos
# porque carteira e permissões mudam mais do que cadastro de contato.
_TTL_CLIENTE = 900
_TTL_REPRESENTANTE = 300

_AJUDA_CLIENTE = (
    "Posso enviar a tabela atual ou consultar um artigo. "
    "Exemplos: “lista de preços” ou “75/36 urdume”."
)

# Não é um erro nem um "em breve" genérico: diz o que fazer agora.
_AJUDA_REPRESENTANTE = (
    "Este número está cadastrado como representante. A consulta de carteira e "
    "de tabela por cliente ainda não está disponível no WhatsApp — use o portal. "
    "A tabela enviada por aqui é a do cadastro de cada cliente."
)

_CAPACIDADES_CLIENTE = [
    Capability(
        id="GET_CURRENT_PRICE_LIST",
        action="GET_CURRENT_PRICE_LIST",
        mode=CapabilityMode.READ,
        requires_confirmation=False,
        idempotency=Idempotency.NONE,
        title="Tabela de preços",
        description="Envia a tabela de preços vigente do contato.",
        vocabulary=Vocabulary(
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
        ),
        slots=[],
    ),
    Capability(
        id="SEARCH_CURRENT_PRICE_LIST_ITEMS",
        action="SEARCH_CURRENT_PRICE_LIST_ITEMS",
        mode=CapabilityMode.READ,
        requires_confirmation=False,
        idempotency=Idempotency.NONE,
        title="Consultar artigo",
        description=(
            "Consulta artigo, preço, disponibilidade ou previsão de chegada na "
            "tabela vigente."
        ),
        vocabulary=Vocabulary(
            # `produto` e `artigo` não são sinônimo de conveniência: eram o
            # comando explícito que o Gateway reconhecia por código no caminho
            # legado. No envelope canônico, nada fora deste manifesto reconhece
            # esses termos — sem eles, "produto PUE 20" deixa de resolver por
            # regra e passa a depender da LLM.
            aliases=[
                "produto",
                "artigo",
                "preço do",
                "preço de",
                "valor do",
                "valor de",
                "quanto está",
                "quanto custa",
                "quando chega",
                "tem",
            ],
            examples=[
                "75/36",
                "tem 75/36 urdume?",
                "preço do PUE 20",
                "quando chega o 100/36?",
            ],
        ),
        # `product_code` é o tipo registrado que reconhece `75/36` sem depender
        # da LLM. O padrão mora no Gateway; aqui só o nome dele (ADR-025).
        slots=[Slot(id="product_query", required=True, kind=SlotKind.PRODUCT_CODE)],
    ),
]


def build_manifest(actor: WhatsappActor, channel_context: ChannelContext) -> CapabilityManifest:
    representante = actor.role is ActorRole.REPRESENTATIVE
    return CapabilityManifest(
        actor=Actor(id=actor.public_ref, role=actor.role.value),
        channel_context=channel_context,
        expires_in_seconds=_TTL_REPRESENTANTE if representante else _TTL_CLIENTE,
        capabilities=[] if representante else list(_CAPACIDADES_CLIENTE),
        help_message=_AJUDA_REPRESENTANTE if representante else _AJUDA_CLIENTE,
    )
