from fastapi import  HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from src.core.settings import app_settings

settings = app_settings()

api_key_header = APIKeyHeader(name=settings.API_KEY_NAME, auto_error=False)

def verify_api_key(api_key_secret: str = Security(api_key_header)):
    if api_key_secret != settings.API_KEY_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key_secret