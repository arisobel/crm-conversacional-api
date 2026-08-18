"""Montagem do manifesto de capacidades por ator.

Uma regra governa tudo aqui: **só entra capacidade cujo executor já exista no
Gateway.** A allowlist de lá recusa o manifesto inteiro por causa de uma ação
desconhecida, e um manifesto recusado deixa o contato sem resposta. Anunciar
aqui uma capacidade que ninguém sabe executar não adianta a entrega — atrasa a
de todo mundo.

As duas listas são **separadas, e não uma derivada da outra**. Cliente e
representante têm alçadas diferentes, e herança faria uma capacidade nova
aparecer para os dois por descuido, sem ninguém decidir. Os dois executores de
cliente resolvem a tabela pelo telefone de quem escreveu procurando um cliente:
servidos a um representante, responderiam que não há tabela para o cadastro
dele. Os três de representante resolvem pela carteira. Não há caso em que uma
lista sirva ao outro papel.

O pré-cadastro é a única escrita de representante anunciada: o Gateway tem o
executor e a máquina de confirmação para
`CRM_REP_CREATE_CUSTOMER_INTAKE`. Ele abre uma solicitação pendente; não cria
nem autoriza um cliente diretamente.
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

# Derivável apenas do que é anunciado logo abaixo: três leituras e um
# pré-cadastro sujeito a aprovação, nesta ordem.
# Prometer aqui o que o manifesto não declara produz a pior falha do canal — o
# representante pede, nada resolve, e ele conclui que o sistema está quebrado.
_AJUDA_REPRESENTANTE = (
    "Este número está cadastrado como representante. Posso consultar artigo em "
    "preço-base, localizar cliente da sua carteira e enviar a tabela de um "
    "cliente dela. Exemplos: “preço do PUE 20”, “buscar cliente Malhas Silva” "
    "ou “tabela do cliente Malhas Silva”. Também posso abrir pelo WhatsApp o "
    "pré-cadastro de um novo cliente, sujeito a aprovação."
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


# As três leituras da W6. Os identificadores de slot são os que o Gateway lê por
# nome literal — `product_query` e `customer_query` — e ele os valida contra o
# próprio registro `action -> slots esperados`. Um nome diferente aqui passaria
# por toda a validação estrutural e chegaria ao executor vazio.
_CAPACIDADES_REPRESENTANTE = [
    Capability(
        id="CRM_REP_SEARCH_PRICE_ITEMS",
        action="CRM_REP_SEARCH_PRICE_ITEMS",
        mode=CapabilityMode.READ,
        requires_confirmation=False,
        idempotency=Idempotency.NONE,
        title="Consultar artigo em preço-base",
        description=(
            "Consulta artigo na competência vigente, em preço-base, sem conversão "
            "de ICMS — não há cliente na pergunta, logo não há praça de destino."
        ),
        vocabulary=Vocabulary(
            aliases=[
                "produto",
                "artigo",
                "preço do produto",
                "preço do artigo",
                "consultar produto",
                "consultar artigo",
                "buscar produto",
                "buscar artigo",
            ],
            examples=[
                "produto PUE 20",
                "artigo 75/36",
                "preço do produto 100/36",
                "buscar artigo urdume texturizado",
            ],
        ),
        slots=[Slot(id="product_query", required=True, kind=SlotKind.PRODUCT_CODE)],
    ),
    Capability(
        id="CRM_REP_LOOKUP_CUSTOMER",
        action="CRM_REP_LOOKUP_CUSTOMER",
        mode=CapabilityMode.READ,
        requires_confirmation=False,
        idempotency=Idempotency.NONE,
        title="Localizar cliente",
        description="Localiza cliente pelo nome, razão social ou documento.",
        vocabulary=Vocabulary(
            aliases=[
                "cliente",
                "procurar cliente",
                "buscar cliente",
                "localizar cliente",
                "consultar cliente",
            ],
            examples=[
                "buscar cliente Malhas Silva",
                "localizar cliente Aurora",
                "cliente Tecelagem Aurora",
            ],
        ),
        # Sem `kind`: não existe tipo registrado no Gateway para nome de cliente,
        # e inventar um aqui seria declarar um tipo que ninguém sabe reconhecer.
        slots=[Slot(id="customer_query", required=True)],
    ),
    Capability(
        id="CRM_REP_GET_CUSTOMER_PRICE_LIST",
        action="CRM_REP_GET_CUSTOMER_PRICE_LIST",
        mode=CapabilityMode.READ,
        requires_confirmation=False,
        idempotency=Idempotency.NONE,
        title="Tabela de um cliente",
        description=(
            "Tabela vigente de um cliente, convertida para a UF de entrega dele."
        ),
        vocabulary=Vocabulary(
            # Mais longos que os de `CRM_REP_LOOKUP_CUSTOMER` de propósito: o
            # Gateway resolve pelo alias mais longo, então "tabela do cliente X"
            # cai aqui e "cliente X" cai na busca. Empate entre capacidades
            # diferentes não executa nada — é o desempate que evita isso.
            aliases=[
                "tabela do cliente",
                "tabela de preços do cliente",
                "consultar tabela do cliente",
                "preço do cliente",
                "preços para cliente",
                "tabela do",
                "lista do",
            ],
            examples=[
                "tabela do cliente Malhas Silva",
                "tabela de preços do cliente Aurora",
                "preço do cliente Tecelagem Aurora",
            ],
        ),
        slots=[Slot(id="customer_query", required=True)],
    ),
    Capability(
        id="CRM_REP_CREATE_CUSTOMER_INTAKE",
        action="CRM_REP_CREATE_CUSTOMER_INTAKE",
        mode=CapabilityMode.WRITE,
        requires_confirmation=True,
        # O Gateway substitui a chave pelo wamid da confirmação e a repassa ao
        # endpoint do CRM. `required` é, portanto, parte da garantia contra
        # reentrega da confirmação, não apenas uma convenção do manifesto.
        idempotency=Idempotency.REQUIRED,
        title="Pré-cadastrar cliente",
        description=(
            "Abre um pré-cadastro de cliente para aprovação no CRM; não ativa "
            "o cliente nem autoriza seu telefone no WhatsApp."
        ),
        vocabulary=Vocabulary(
            aliases=[
                "cadastrar cliente",
                "novo cliente",
                "incluir cliente",
                "criar cliente",
                "pré-cadastrar cliente",
            ],
            examples=[
                "cadastrar cliente Malhas Silva Ltda",
                "quero pré-cadastrar um novo cliente",
            ],
        ),
        # Os dois primeiros são o contrato de execução. Os demais são
        # coletados opcionalmente pela mesma conversa do Gateway e enviados ao
        # endpoint quando informados.
        slots=[
            Slot(id="customer_legal_name", required=True),
            Slot(id="customer_state_code", required=True),
            Slot(id="customer_whatsapp", required=False),
            Slot(id="preferred_products_text", required=False),
        ],
    ),
]


def build_manifest(actor: WhatsappActor, channel_context: ChannelContext) -> CapabilityManifest:
    representante = actor.role is ActorRole.REPRESENTATIVE
    return CapabilityManifest(
        actor=Actor(id=actor.public_ref, role=actor.role.value),
        channel_context=channel_context,
        expires_in_seconds=_TTL_REPRESENTANTE if representante else _TTL_CLIENTE,
        # Listas separadas, nunca uma somada à outra: são alçadas diferentes.
        capabilities=list(
            _CAPACIDADES_REPRESENTANTE if representante else _CAPACIDADES_CLIENTE
        ),
        help_message=_AJUDA_REPRESENTANTE if representante else _AJUDA_CLIENTE,
    )
