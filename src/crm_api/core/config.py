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

    # Forma de converter o preço-base entre UFs. `INSIDE` é o cálculo "por
    # dentro", em que o ICMS compõe a própria base — a convenção brasileira e a
    # proposta pendente de confirmação contábil (Q1/Q2). `OUTSIDE` trata o
    # imposto como acréscimo sobre o líquido. Trocar aqui não altera o banco.
    icms_conversion_mode: str = "INSIDE"

    # Se a tabela enviada pelo WhatsApp já vai convertida para a UF do cliente.
    # Desligado por padrão, e o motivo é o alcance: no portal um representante
    # confere o `trace` antes de cotar; no WhatsApp o número vai direto ao
    # cliente. Sem este interruptor, carregar a matriz de ICMS para usar o
    # portal mudaria, como efeito colateral, o que o cliente recebe.
    whatsapp_icms_enabled: bool = False

    # Retenção do histórico de interações, em dias. Sem valor o expurgo recusa
    # rodar: por quanto tempo conteúdo de conversa pode ficar guardado é decisão
    # de LGPD (Q3), e um padrão embutido no código a tomaria em silêncio.
    interaction_retention_days: int | None = None

    # `/docs` e `/redoc` expõem toda a superfície administrativa a quem apenas
    # alcança a URL. Desligados por padrão: quem precisa da documentação
    # interativa liga em desenvolvimento, e não o contrário.
    expose_api_docs: bool = False

    password_min_length: int = 12
    login_max_failed_attempts: int = 5
    login_lockout_seconds: int = 900
    login_rate_limit_attempts: int = 20
    login_rate_limit_window_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
