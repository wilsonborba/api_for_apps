import time
from fastapi import  HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi import HTTPException, Security, Request, Response, Depends

from src.presentation.handler.exchange_auth_app_handler import get_nonce_from_redis_sync, get_user_info_from_redis_sync
from src.core.utils import get_redis_adapter
from src.core.settings import app_settings
from src.core.logs import error, warning

settings = app_settings()

api_admin_key_header = APIKeyHeader(name=settings.API_ADMIN_KEY_NAME, auto_error=False)

def verify_auth(request: Request, response: Response, api_key_secret: str = Security(api_admin_key_header)):
    """
    Verify the API key from the request header or cookies.

    The api_admin_key is checked first in the request headers. (this is a private admin usage for dev or internal purpose)
    it simplify the process of checking the routes functionalities instead of using cookies (used for prod and users)


    """

    # verify if headers contains the API_ADMIN_KEY_NAME key 
    # if not skip validation
    
    
    if api_key_secret and api_key_secret != settings.API_KEY_SECRET:
        error(f"Invalid API Key...")
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    if api_key_secret and api_key_secret == settings.API_KEY_SECRET:

        return api_key_secret


    adapter = get_redis_adapter(request)

    headers = request.headers
    cookies = request.cookies

    http_only_cookie = cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)
    public_cookie = cookies.get(settings.PUBLIC_COOKIE_KEY_NAME)

    actual_nonce_headers = headers.get(settings.ACTUAL_AUTH_NONCE_HEADER_KEY_NAME)

    temporary_nonce_headers = headers.get(settings.TEMPORARY_AUTH_NONCE_HEADER_KEY_NAME)

    user_info = get_user_info_from_redis_sync(adapter=adapter, session_id=http_only_cookie)
    
    if not actual_nonce_headers or not temporary_nonce_headers:
        error(f"Missing Headers {settings.ACTUAL_AUTH_NONCE_HEADER_KEY_NAME} and {settings.TEMPORARY_AUTH_NONCE_HEADER_KEY_NAME}...")
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    actual_nonce_redis = get_nonce_from_redis_sync(adapter, actual_nonce_headers)
    temporary_nonce_redis = get_nonce_from_redis_sync(adapter, temporary_nonce_headers)

    if not actual_nonce_redis or not temporary_nonce_redis:
        error(f"Missing/Not Found Nonce in Redis...")
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")



    is_valid_temporary_nonce = temporary_nonce_redis.get("is_valid", False)

    if not is_valid_temporary_nonce:
        is_not_valid_since = temporary_nonce_redis.get("is_not_valid_since")
        int_time_now = int(time.time())
        
        # verify is the substraction is more than 0,5 minutes (30 seconds)

        if (int_time_now - is_not_valid_since > 30):
            error(f"Expired Nonce... {is_not_valid_since} - {int_time_now} > 30")
            raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")
        
        warning(f"The nonce is not valid, but still in grace period...")

        if not http_only_cookie or not public_cookie:
            error(f"Missing Cookies...")
            raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")
        
        user_nonce_id = user_info.get("nonce_id", None)

        if actual_nonce_headers != user_nonce_id:
            error(f"Invalid Nonce...")
            raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")
        
    