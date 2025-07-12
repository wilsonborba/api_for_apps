# src/core/settings.py

from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv

from src.domain.models.db_config_model import DatabaseConfig

load_dotenv()  # Loads .env file

class Settings(BaseSettings):
    # API
    API_KEY_NAME: str = "Authorization"
    API_KEY_SECRET: str  # Will be loaded from .env
    DEFAULT_DB_HOST: str
    DEFAULT_DB_PORT: int
    DEFAULT_DB_USER: str
    DEFAULT_DB_PASSWORD: str
    DEFAULT_DB_NAME: str
    DEFAULT_DB_SSLMODE: str = "require"  # Default SSL mode for PostgreSQL
    FIREBASE_SERVICE_ACCOUNT_PATH: str = "./firebase.json"  # Path to Firebase service account JSON file
    FERNET_KEY_SECRET: str  # Secret key for Fernet encryption, loaded from .env

    # Development flag
    development_mode: bool = True

    @property
    def default_db(self) -> DatabaseConfig:
        return DatabaseConfig(
            dialect="postgresql",
            username=self.DEFAULT_DB_USER,
            password=self.DEFAULT_DB_PASSWORD,
            host=self.DEFAULT_DB_HOST,
            port=self.DEFAULT_DB_PORT,
            database=self.DEFAULT_DB_NAME,
            options={"sslmode": self.DEFAULT_DB_SSLMODE}
        )

    class Config:
        env_file = ".env"  # Optional with load_dotenv, but good for pydantic to know

# Singleton
@lru_cache()
def app_settings() -> Settings:
    return Settings()