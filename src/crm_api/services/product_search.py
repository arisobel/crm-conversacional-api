"""Casamento de termos de busca de artigo.

Extraído de `services/price_lists.py` quando a busca passou a ter dois
chamadores: a do cliente, pela tabela dele, e a do representante, pelo catálogo
da competência em preço-base. As funções são as mesmas, byte a byte — a busca
por `75/36` precisa se comportar igual nos dois lados, e duas cópias
divergiriam na primeira correção.
"""

import re
import unicodedata

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
