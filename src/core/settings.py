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
    FERNET_KEY_SECRET: str  # Secret key for Fernet encryption, loaded from .env

    # private server key for fernet encryption/decryption
    SERVER_FERNET_KEY_SECRET: str  # Secret key for Fernet encryption, loaded

    # headers auth key name
    NEXT_AUTH_NONCE_HEADER_KEY_NAME: str = "N-A-N"  # Example header key name
    ACTUAL_AUTH_NONCE_HEADER_KEY_NAME: str = "A-A-N"  # Example header key name
    TEMPORARY_AUTH_NONCE_HEADER_KEY_NAME: str = "T-A-N"  # Example header key name

    # cookies key name
    HTTP_ONLY_COOKIE_KEY_NAME: str = "sid"
    PUBLIC_COOKIE_KEY_NAME: str = "hint"

    # REDIS
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    REDIS_NAMESPACE: str = "api_for_apps:"

    # redis cache prefix
    CACHE_AUTH_PREFIX: str = "exchange_auth_app"

    # Development flag
    development_mode: bool = True

    # Public proxy routes (app -> list of path patterns)
    PUBLIC_PROXY_ROUTE_ALLOWLIST: Dict[str, List[str]] = {
        "certifications": ["/quiz/certifications/*"]
    }
    PUBLIC_PROXY_ALLOWED_METHODS: Tuple[str, ...] = ("GET", "HEAD", "OPTIONS")

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
