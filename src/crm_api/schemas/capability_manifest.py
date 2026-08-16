"""Envelope `business-capability-manifest/v1`.

As restrições aqui não são preferência de estilo: elas espelham, campo a campo,
o `business_capability_manifest_v1.schema.json` do Gateway. Lá o manifesto é
recusado **inteiro** quando qualquer uma falha — não há aceitação parcial —, e
um manifesto recusado deixa o contato sem resposta. Validar na emissão é o que
transforma esse erro numa falha de teste aqui em vez de num silêncio lá.

Fonte: `arisobel/whatsapp-webhook-caprover`, `docs/04_technical/`, commit
`e122bb6`. Ver ADR-022, ADR-025 e ADR-026.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "business-capability-manifest/v1"
PROVIDER = "crm_api"

_ACTOR_ID = r"^[a-f0-9]{24}$"
_SLOT_ID = r"^[a-z][a-z0-9_]{0,39}$"
_LINE_ID = r"^\d{5,64}$"
_ALIAS = Field(min_length=1, max_length=80, pattern=r"\S")
_EXAMPLE = Field(min_length=1, max_length=240, pattern=r"\S")


class CapabilityMode(StrEnum):
    READ = "read"
    WRITE = "write"


class Idempotency(StrEnum):
    NONE = "none"
    REQUIRED = "required"


class SlotKind(StrEnum):
    """Tipos registrados no Gateway.

    O manifesto declara o tipo e **nunca** o padrão: expressão regular de origem
    remota é ReDoS e superfície de injeção (ADR-025). Acrescentar um valor aqui
    exige deploy do Gateway e atualização coordenada do schema compartilhado —
    por isso a regra é vocabulário primeiro, tipo por exceção (ADR-026).
    """

    PRODUCT_CODE = "product_code"


class ChannelContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["whatsapp"] = "whatsapp"
    line_phone_number_id: str | None = Field(default=None, pattern=_LINE_ID)


class ManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_phone_e164: str = Field(min_length=8, max_length=20)
    channel_context: ChannelContext


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_ACTOR_ID)
    role: str = Field(min_length=1)


class Vocabulary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Alias ou exemplo em branco casaria com qualquer mensagem; o Gateway recusa
    # o manifesto inteiro por causa de um.
    aliases: list[Annotated[str, _ALIAS]] = Field(
        default_factory=list,
        max_length=32,
        description="Sinônimos que resolvem por regra, antes de qualquer LLM.",
    )
    examples: list[Annotated[str, _EXAMPLE]] = Field(default_factory=list, max_length=16)


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_SLOT_ID)
    # Explícito de propósito: o contrato não admite obrigatoriedade implícita.
    required: bool
    kind: SlotKind | None = None


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    mode: CapabilityMode
    requires_confirmation: bool
    idempotency: Idempotency
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    vocabulary: Vocabulary | None = None
    slots: list[Slot] | None = Field(default=None, max_length=16)


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    provider: Literal[PROVIDER] = PROVIDER
    actor: Actor
    channel_context: ChannelContext
    # Teto do Gateway, não escolha nossa: ele recusa acima de 900. O ADR-012
    # fixava 30 minutos, e é essa parte dele que o ADR-022 revoga.
    expires_in_seconds: int = Field(ge=1, le=900)
    capabilities: list[Capability]
    help_message: str = Field(min_length=1, max_length=1000)
