# src/core/settings.py

from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()  # Loads .env file

class Settings(BaseSettings):
    # API
    API_KEY_NAME: str = "Authorization"
    API_KEY_SECRET: str  # Will be loaded from .env

    # Development flag
    development_mode: bool = True

    class Config:
        env_file = ".env"  # Optional with load_dotenv, but good for pydantic to know

# Singleton
@lru_cache()
def app_settings() -> Settings:
    return Settings()