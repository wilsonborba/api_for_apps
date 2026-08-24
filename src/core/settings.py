# src/core/settings.py


from typing import Dict, List, Tuple
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.domain.models.db_config_model import DatabaseConfig

load_dotenv()  # Loads .env file


class Settings(BaseSettings):
    # Existing local .env files can contain retired Firebase/development keys;
    # ignore those rather than turning a non-secret compatibility setting into
    # a startup failure.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    # API
    API_ADMIN_KEY_NAME: str = "Authorization"
    API_KEY_SECRET: str  # Will be loaded from .env
    DEFAULT_DB_HOST: str
    DEFAULT_DB_PORT: int
    DEFAULT_DB_USER: str
    DEFAULT_DB_PASSWORD: str
    DEFAULT_DB_NAME: str
    DEFAULT_DB_SSLMODE: str = "require"  # Default SSL mode for PostgreSQL
    # Supabase is the only runtime identity provider.  The Firebase fields in
    # older database rows remain a schema compatibility concern, not an auth
    # integration.
    AUTH_PROVIDER: str = "supabase"
    SUPABASE_URL: str = ""
    SUPABASE_PROJECT_REF: str = ""
    # Server-only credential. Frontends never communicate with Supabase.
    SUPABASE_SECRET_KEY: str
    FERNET_KEY_SECRET: str  # Secret key for Fernet encryption, loaded from .env

    # private server key for fernet encryption/decryption
    SERVER_FERNET_KEY_SECRET: str  # Secret key for Fernet encryption, loaded

    # cookies key name
    HTTP_ONLY_COOKIE_KEY_NAME: str = "sid"
    CSRF_COOKIE_KEY_NAME: str = "csrf"

    # REDIS
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    REDIS_NAMESPACE: str = "api_for_apps:"

    # redis cache prefix
    CACHE_AUTH_PREFIX: str = "exchange_auth_app"
    EXCHANGE_ARTIFACT_PREFIX: str = "exchange_artifact"
    OAUTH_STATE_PREFIX: str = "oauth_state"
    SESSION_TTL_SECONDS: int = 60 * 60 * 25
    CSRF_TTL_SECONDS: int = 60 * 60 * 24
    EXCHANGE_ARTIFACT_TTL_SECONDS: int = 60
    DEFAULT_EXCHANGE_APP: str = "certifications"
    EXCHANGE_ALLOWED_APPS: Tuple[str, ...] = ("certifications",)

    # Runtime mode is selected by the development/production launch script.
    environment: str = "development"
    ASODYA_MAIN_DOMAIN: str = "asodya.com"
    AUTH_APP_LOCAL_URL: str = "http://192.168.1.103:8100"
    AUTH_APP_PROD_URL: str = "https://auth.asodya.com"
    COOKIE_DOMAIN_PROD: str = ".asodya.com"

    # Public proxy routes (app -> list of path patterns)
    PUBLIC_PROXY_ROUTE_ALLOWLIST: Dict[str, List[str]] = {
        "certifications": ["/quiz/certifications/*"]
    }
    PUBLIC_PROXY_ALLOWED_METHODS: Tuple[str, ...] = ("GET", "HEAD", "OPTIONS")
    OAUTH_PROVIDERS: Tuple[str, ...] = ("google", "github", "microsoft", "azure")

    @property
    def auth_app_callback_url(self) -> str:
        base_url = self.AUTH_APP_LOCAL_URL if self.development_mode else self.AUTH_APP_PROD_URL
        return f"{base_url}/callback"

    @property
    def auth_app_reset_url(self) -> str:
        base_url = self.AUTH_APP_LOCAL_URL if self.development_mode else self.AUTH_APP_PROD_URL
        return f"{base_url}/reset-password"

    @property
    def cookie_domain(self) -> str | None:
        if self.development_mode:
            return None
        return self.COOKIE_DOMAIN_PROD

    @property
    def development_mode(self) -> bool:
        return self.environment.lower() in {"development", "dev", "local"}

    @property
    def default_db(self) -> DatabaseConfig:
        return DatabaseConfig(
            dialect="postgresql",
            username=self.DEFAULT_DB_USER,
            password=self.DEFAULT_DB_PASSWORD,
            host=self.DEFAULT_DB_HOST,
            port=self.DEFAULT_DB_PORT,
            database=self.DEFAULT_DB_NAME,
            options={"sslmode": self.DEFAULT_DB_SSLMODE},
        )

    # Schema related settings

    class AvailableApps:
        api = "/api"
        certifications = "/certifications"

    @property
    def available_apps(self) -> AvailableApps:
        return self.AvailableApps()


# Singleton
@lru_cache()
def app_settings() -> Settings:
    return Settings()
