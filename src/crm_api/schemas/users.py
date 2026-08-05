from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from crm_api.models.user import UserRole

_E164 = r"^\+[1-9][0-9]{7,14}$"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    full_name: str
    email: str
    role: UserRole
    whatsapp_e164: str | None
    active: bool
    last_login_at: datetime | None


class UserPage(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1)
    role: UserRole = UserRole.REPRESENTATIVE
    whatsapp_e164: str | None = Field(default=None, pattern=_E164)


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: UserRole | None = None
    whatsapp_e164: str | None = Field(default=None, pattern=_E164)


class SetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=1)
