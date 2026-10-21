"""Regras de horário para a rotina diária da linha assistente.

O chamador fornece a data e hora no fuso configurado do representante e as
rotinas já realizadas naquele dia. Este módulo não agenda nem envia mensagens.
"""

from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo


class AssistantRoutine(StrEnum):
    START_DAY = "START_DAY"
    END_DAY = "END_DAY"


START_TIME = time(7, 30)
END_TIME = time(18, 30)
DEFAULT_TIMEZONE = "America/Sao_Paulo"


def due_routines(
    local_now: datetime, completed_today: set[AssistantRoutine]
) -> list[AssistantRoutine]:
    """Retorna as rotinas vencidas que ainda não foram realizadas no dia local.

    Antecipar uma rotina conta como realização e evita sua repetição no horário
    padrão. Persistência, concorrência, entrega e validade de tentativas são
    responsabilidades do futuro executor, não desta função.
    """
    if local_now.utcoffset() is None:
        raise ValueError("local_now must include the configured timezone")

    current_time = local_now.timetz().replace(tzinfo=None)
    schedule = (
        (AssistantRoutine.START_DAY, START_TIME),
        (AssistantRoutine.END_DAY, END_TIME),
    )
    return [
        routine
        for routine, scheduled_time in schedule
        if current_time >= scheduled_time and routine not in completed_today
    ]


def due_routines_brasilia(
    now: datetime, completed_today: set[AssistantRoutine]
) -> list[AssistantRoutine]:
    """Aplica o horário de Brasília a um instante com fuso explícito.

    ``completed_today`` deve corresponder à data local de Brasília, inclusive
    quando a data UTC for diferente.
    """
    if now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return due_routines(now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)), completed_today)
