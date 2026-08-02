from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CRM_", extra="ignore")

    database_url: str
    tenant_slug: str
    internal_hmac_secret: SecretStr
    internal_hmac_previous_secret: SecretStr | None = None
    internal_hmac_tolerance_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
