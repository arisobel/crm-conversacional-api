from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from crm_api.models.user import UserRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    # `SecretStr` mantém a senha fora de `repr`, de logs de validação e de
    # qualquer serialização acidental do corpo da requisição.
    password: SecretStr = Field(min_length=1)


class AuthenticatedUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    tenant_id: UUID
    full_name: str
    email: str
    role: UserRole
