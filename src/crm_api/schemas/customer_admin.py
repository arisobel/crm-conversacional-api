from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_E164 = r"^\+?[0-9\s().-]{8,20}$"


class CreateCustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str = Field(min_length=1, max_length=300)
    state_code: str = Field(min_length=2, max_length=2)
    trade_name: str | None = Field(default=None, max_length=300)
    document_number: str | None = Field(default=None, max_length=32)
    owner_user_id: UUID | None = Field(
        default=None,
        description="Ignorado quando quem cria é REPRESENTATIVE: o titular vira o autor.",
    )


class UpdateCustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str | None = Field(default=None, min_length=1, max_length=300)
    trade_name: str | None = Field(default=None, max_length=300)
    document_number: str | None = Field(default=None, max_length=32)
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    active: bool | None = None


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contact_id: UUID
    name: str
    whatsapp_e164: str
    is_primary: bool
    active: bool


class CreateContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    # Aceita a forma de apresentação; a normalização para E.164 acontece no
    # serviço, que também é quem recusa o que não for telefone válido.
    whatsapp_e164: str = Field(pattern=_E164)
    is_primary: bool = False


class UpdateContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    whatsapp_e164: str | None = Field(default=None, pattern=_E164)
    is_primary: bool | None = None
    active: bool | None = None


class LocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: UUID
    label: str
    state_code: str
    city: str | None
    is_default: bool
    active: bool


class CreateLocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    state_code: str = Field(min_length=2, max_length=2)
    city: str | None = Field(default=None, max_length=200)
    is_default: bool = False


class UpdateLocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=200)
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    city: str | None = Field(default=None, max_length=200)
    is_default: bool | None = None
    active: bool | None = None
