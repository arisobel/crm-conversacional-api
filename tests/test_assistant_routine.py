from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from crm_api.services.assistant_routine import (
    AssistantRoutine,
    due_routines,
    due_routines_brasilia,
)


def moment(hour: int, minute: int, day: int = 21) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo("America/Sao_Paulo"))


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (7, 29, []),
        (7, 30, [AssistantRoutine.START_DAY]),
        (18, 29, [AssistantRoutine.START_DAY]),
        (18, 30, [AssistantRoutine.START_DAY, AssistantRoutine.END_DAY]),
    ],
)
def test_daily_schedule(hour, minute, expected):
    assert due_routines(moment(hour, minute), set()) == expected


def test_early_completion_prevents_repeat_at_scheduled_time():
    completed = {AssistantRoutine.START_DAY, AssistantRoutine.END_DAY}
    assert due_routines(moment(18, 30), completed) == []


def test_completion_is_supplied_for_each_local_day():
    assert due_routines(moment(7, 30, day=22), set()) == [AssistantRoutine.START_DAY]


def test_naive_time_is_rejected():
    with pytest.raises(ValueError):
        due_routines(datetime(2026, 10, 21, 7, 30), set())


def test_utc_instant_is_converted_to_brasilia_schedule():
    assert due_routines_brasilia(datetime(2026, 10, 21, 10, 30, tzinfo=UTC), set()) == [
        AssistantRoutine.START_DAY
    ]
