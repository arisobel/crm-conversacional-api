"""Canonização de texto digitado que precisa ser comparado, não exibido."""

import re
import unicodedata

_ESPACOS = re.compile(r"\s+")


def strip_accents(value: str) -> str:
    decomposto = unicodedata.normalize("NFKD", value)
    return "".join(letra for letra in decomposto if not unicodedata.combining(letra))


def normalize_group_name(value: str) -> str:
    """Forma canônica de um nome de grupo de artigo.

    Sem acento, em caixa baixa e com os espaços internos colapsados, para que
    `Poliéster`, `poliester` e `POLIÉSTER  ` sejam reconhecidos como o mesmo
    grupo. É o valor que a unicidade do banco compara — o nome digitado é
    preservado à parte, porque é ele que aparece na tela.
    """
    return _ESPACOS.sub(" ", strip_accents(value).casefold()).strip()
