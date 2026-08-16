"""Identificador público de ator, no formato que o Gateway aceita.

O `business-capability-manifest/v1` valida `actor.id` contra `^[a-f0-9]{24}$`:
exatamente 24 hexadecimais, 12 bytes, nem mais nem menos.

Ele é sorteado e guardado, e não derivado do UUID por HMAC. Derivar dispensaria
a coluna, mas amarraria a identidade do ator à rotação do segredo — girar a
chave mudaria todos os identificadores de uma vez, invalidando o cache do
Gateway e partindo em dois o histórico de observação que ele persiste por
contexto. Um identificador estável não pode depender de um valor que existe
para ser trocado.
"""

import re
import secrets

PUBLIC_REF_PATTERN = re.compile(r"^[a-f0-9]{24}$")
_PUBLIC_REF_BYTES = 12


def new_public_ref() -> str:
    """Sorteia um identificador público novo, com 96 bits de entropia."""
    return secrets.token_hex(_PUBLIC_REF_BYTES)


def is_public_ref(value: str) -> bool:
    return bool(PUBLIC_REF_PATTERN.fullmatch(value))
