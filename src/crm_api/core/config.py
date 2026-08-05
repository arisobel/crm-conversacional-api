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

    # Sessão do portal. Independente do HMAC do Gateway: papéis administrativos
    # nunca são concedidos por uma chamada assinada entre serviços.
    session_cookie_name: str = "crm_session"
    session_ttl_seconds: int = 1800
    session_absolute_ttl_seconds: int = 43200
    session_cookie_secure: bool = True

    password_min_length: int = 12
    login_max_failed_attempts: int = 5
    login_lockout_seconds: int = 900
    login_rate_limit_attempts: int = 20
    login_rate_limit_window_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
