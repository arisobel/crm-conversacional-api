"""Casamento de termos de busca de artigo.

Extraído de `services/price_lists.py` quando a busca passou a ter dois
chamadores: a do cliente, pela tabela dele, e a do representante, pelo catálogo
da competência em preço-base. As funções são as mesmas, byte a byte — a busca
por `75/36` precisa se comportar igual nos dois lados, e duas cópias
divergiriam na primeira correção.
"""

import re
import unicodedata
from difflib import SequenceMatcher

from crm_api.schemas.price_lists import CurrentPriceListItemResponse

_SEARCH_SEPARATOR = re.compile(r"[^a-z0-9]+")

# Artigos e preposições que chegam colados no termo quando quem extrai o slot
# não os remove — "quanto está o PUE 20" produz `o PUE 20`. Como o casamento
# exige **todos** os termos, um "o" sozinho fazia a busca não encontrar um
# produto que existe, e a resposta era "não encontrei" em vez do preço.
_RUIDO = frozenset(
    {
        "o", "a", "os", "as", "um", "uma", "uns", "umas",
        "de", "do", "da", "dos", "das", "no", "na", "nos", "nas",
        "em", "para", "pra", "com", "e", "ao", "aos",
    }
)

_RUIDO_COMERCIAL = frozenset(
    {
        "preco", "precos", "valor", "valores", "produto", "produtos",
        "artigo", "artigos", "consultar", "buscar", "procurar", "queria",
    }
)

def search_tokens(value: str) -> list[str]:
    """Termos de busca, sem acento, em caixa baixa e sem ruído gramatical.

    O ruído só é descartado quando sobra alguma coisa: uma mensagem que seja
    apenas "de" continua sendo pesquisada como "de" em vez de virar busca vazia,
    que casaria com o catálogo inteiro.
    """
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    tokens = [token for token in _SEARCH_SEPARATOR.split(ascii_value.casefold()) if token]
    significativos = [token for token in tokens if token not in _RUIDO]
    return significativos or tokens


def matches_search_terms(item: CurrentPriceListItemResponse, terms: list[str]) -> bool:
    searchable_value = " ".join(
        part
        for part in (item.sku, item.display_name, item.specification, item.family_name)
        if part
    )
    searchable_tokens = set(search_tokens(searchable_value))
    return all(term in searchable_tokens for term in terms)


def _similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.86
    return SequenceMatcher(None, left, right).ratio()


def fuzzy_search_score(item: CurrentPriceListItemResponse, query: str) -> float:
    """Pontua uma sugestão sem transformá-la em correspondência confirmada.

    Cada termo digitado precisa ter um candidato razoável no artigo. Isso lida
    com transposição e erro curto (``PUE`` → ``PEU``), mas evita que uma única
    palavra parecida esconda o restante de uma consulta diferente. O valor é
    usado apenas para ordenar sugestões; preço nunca é liberado por este score.
    """
    raw_query_terms = search_tokens(query)
    query_terms = [term for term in raw_query_terms if term not in _RUIDO_COMERCIAL]
    query_terms = query_terms or raw_query_terms
    if not query_terms:
        return 0.0
    searchable_value = " ".join(
        part
        for part in (item.sku, item.display_name, item.specification, item.family_name)
        if part
    )
    candidate_terms = search_tokens(searchable_value)
    if not candidate_terms:
        return 0.0
    return sum(
        max(_similarity(term, candidate) for candidate in candidate_terms)
        for term in query_terms
    ) / len(query_terms)


def suggest_search_items[Item: CurrentPriceListItemResponse](
    items: list[Item], query: str, *, limit: int = 3, minimum_score: float = 0.55
) -> list[Item]:
    """Devolve os artigos mais próximos para uma pergunta de confirmação.

    A função não mistura sugestões com resultados exatos. Quem chama só deve
    usá-la quando a busca normal não encontrou nada e deve pedir confirmação ao
    usuário antes de consultar/exibir o preço do artigo sugerido.
    """
    ranked = [
        (fuzzy_search_score(item, query), item)
        for item in items
    ]
    eligible = [(score, item) for score, item in ranked if score >= minimum_score]
    eligible.sort(key=lambda pair: (-pair[0], pair[1].display_name, pair[1].sku))
    return [item for _score, item in eligible[:limit]]
