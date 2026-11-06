from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ReminderKindValue = Literal["CALL", "MEETING", "FOLLOW_UP"]


class CustomerReminderRequest(BaseModel):
    gateway_line_reference: str = Field(min_length=1, max_length=200)
    customer_phone_e164: str = Field(min_length=8, max_length=20)
    source_wamid: str = Field(min_length=1, max_length=255)
    kind: ReminderKindValue
    due_at: datetime
    note: str = Field(min_length=2, max_length=500)


class CustomerReminderResponse(BaseModel):
    created: bool
    reminder_id: UUID
    status: str
    representative_phone_e164: str
    representative_name: str
    customer_name: str
    due_at: datetime
    kind: ReminderKindValue


class ReminderNotificationClaimRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)


class ReminderNotificationItem(BaseModel):
    reminder_id: UUID
    claim_token: UUID
    representative_phone_e164: str
    representative_name: str
    customer_name: str | None = None
    due_at: datetime
    kind: ReminderKindValue
    note: str


class ReminderNotificationClaimResponse(BaseModel):
    reminders: list[ReminderNotificationItem]


class ReminderNotificationAckRequest(BaseModel):
    reminder_id: UUID
    claim_token: UUID
    delivered: bool

