"""Forma canônica de telefone, para todas as bordas do sistema.

Vivia em `services/customers.py` enquanto só contato de cliente tinha telefone.
Com o representante atendido pelo WhatsApp, `users` passa a ter um telefone que
precisa da mesma regra, e um módulo chamado "customers" deixaria de descrever o
que faz.
"""

import re

_PRESENTATION_CHARS = re.compile(r"[\s().-]")
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
# Celular brasileiro na forma anterior à renumeração de 2012: +55, DDD e oito
# dígitos começando em 6-9. Fixo começa em 2-5 e não recebe nono dígito —
# WhatsApp Business pode usar linha fixa, então a distinção não é acadêmica.
_BR_MOBILE_WITHOUT_NINTH = re.compile(r"^\+55([1-9][0-9])([6-9][0-9]{7})$")


class InvalidWhatsappNumber(ValueError):
    pass


def normalize_whatsapp_e164(phone: str) -> str:
    """Forma canônica de telefone: E.164 com "+" e nono dígito aplicado.

    O nono dígito não é formatação, é identidade: `+551188887777` e
    `+5511988887777` são o mesmo assinante, e contas antigas ainda chegam da
    Meta sem ele. Sem resolver as duas grafias para a mesma, um cliente
    cadastrado numa forma e escrevendo da outra não é encontrado — e o cadastro
    aparece correto na tela, sem nada a depurar.
    """
    normalized = _PRESENTATION_CHARS.sub("", phone)
    if not _E164.fullmatch(normalized):
        raise InvalidWhatsappNumber("phone must be a valid E.164 number")
    antiga = _BR_MOBILE_WITHOUT_NINTH.fullmatch(normalized)
    if antiga:
        return f"+55{antiga.group(1)}9{antiga.group(2)}"
    return normalized
