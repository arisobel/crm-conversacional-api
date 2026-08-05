from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OwnerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    full_name: str
    email: str


class CustomerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: UUID
    legal_name: str
    trade_name: str | None
    document_number: str | None
    state_code: str
    active: bool
    owner: OwnerSummary | None


class CustomerPage(BaseModel):
    items: list[CustomerSummary]
    total: int
    limit: int
    offset: int


class OwnerAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: UUID | None = Field(
        default=None,
        description="Nulo remove o titular; a remoção também entra no histórico.",
    )
    reason: str | None = Field(default=None, max_length=500)


class AssignmentHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assigned_at: datetime
    assigned_by: UUID
    reason: str | None
    owner: OwnerSummary | None
