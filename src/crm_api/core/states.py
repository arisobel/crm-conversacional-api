"""Unidades federativas do Brasil.

A validação vive na aplicação porque o `CHECK` do banco só garante o formato de
duas letras maiúsculas: `XX` passa no banco e não é uma UF.
"""

BRAZILIAN_STATES = frozenset(
    {
        "AC",
        "AL",
        "AP",
        "AM",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MT",
        "MS",
        "MG",
        "PA",
        "PB",
        "PR",
        "PE",
        "PI",
        "RJ",
        "RN",
        "RS",
        "RO",
        "RR",
        "SC",
        "SP",
        "SE",
        "TO",
    }
)


class InvalidStateCode(ValueError):
    """UF ausente da lista das 27 unidades federativas."""


def normalize_state_code(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in BRAZILIAN_STATES:
        raise InvalidStateCode(f"'{value}' is not a Brazilian state code")
    return normalized
