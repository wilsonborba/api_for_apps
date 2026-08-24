# src/core/settings.py


from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Dict, List, Tuple
from functools import lru_cache
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

from src.domain.models.db_config_model import DatabaseConfig

load_dotenv()  # Loads .env file


class Settings(BaseSettings):
    # API
    API_ADMIN_KEY_NAME: str = "Authorization"
    API_KEY_SECRET: str  # Will be loaded from .env
    DEFAULT_DB_HOST: str
    DEFAULT_DB_PORT: int
    DEFAULT_DB_USER: str
    DEFAULT_DB_PASSWORD: str
    DEFAULT_DB_NAME: str
    DEFAULT_DB_SSLMODE: str = "require"  # Default SSL mode for PostgreSQL
    FIREBASE_SERVICE_ACCOUNT_PATH: str = (
        "./firebase.json"  # Path to Firebase service account JSON file
    )
    AUTH_PROVIDER: str = "firebase"
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_PROJECT_REF: str = ""
    SUPABASE_SECRET_KEY: str = ""
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
    OAUTH_STATE_PREFIX: str = "oauth_state"

    # Runtime mode is selected by the development/production launch script.
    environment: str = "development"
    ASODYA_MAIN_DOMAIN: str = "asodya.com"
    AUTH_APP_LOCAL_URL: str = "http://192.168.1.103:8100"
    AUTH_APP_PROD_URL: str = "https://auth.asodya.com:8100"
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

    class Config:
        env_file = ".env"  # Optional with load_dotenv, but good for pydantic to know

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
