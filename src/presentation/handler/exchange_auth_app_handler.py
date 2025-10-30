



from fastapi import Request
from src.dal.local.redis_adapter import RedisAdapter
from src.domain.models.user_model import UserCookieModel
from src.core.settings import app_settings
from src.presentation.handler.responses import ExchangeAuthError
from src.domain.services.exchange_auth_app_service import ExchangeAuthService


exchange_auth_service = ExchangeAuthService()
settings = app_settings()



def exchange_auth_sync(token: str) -> str:
    loaded_decrypted_token = exchange_auth_service.decrypt_token(token)
    is_valid, error_message = exchange_auth_service.validate_token(loaded_decrypted_token)
    
    if not is_valid:
        raise ExchangeAuthError(error_message)
    

    user_cookie = exchange_auth_service.build_user_cookie(loaded_decrypted_token)
    
    return user_cookie


async def set_http_only_cookies_for_auth_sync(adapter: RedisAdapter, request: Request, response, user_cookie: UserCookieModel):
    """The user_cookie is a session_id key generated that will be queryed in redis to get user info"""

    # prepare user_cookie transformed json

    # max age is in seconds so for example 15 minutes is 15 * 60 = 900 seconds
    # if we have int(time.time()) + 15 * 60 it will be expire in 15 minutes from now

    is_https = request.url.scheme == "https"

    

    response.set_cookie(
        key=settings.HTTP_ONLY_COOKIE_KEY_NAME,
        value=user_cookie.session_id,
        httponly=True,
        secure=is_https,
        samesite="Lax",
        max_age=1 * 24 * 60 * 60 + 1 * 60 * 60  # 1 day and 1 hour
    )

    # save the session id in the redis

    key = adapter.k(settings.CACHE_AUTH_PREFIX, user_cookie.session_id)

    await adapter.set(
        key=key,
        value=user_cookie.to_dict(),
        ex=1 * 24 * 60 * 60 + 1 * 60 * 60  # 1 day and 1 hour
    )

    return response

async def set_public_cookies_for_auth_sync(adapter: RedisAdapter, request: Request, response, user_cookie: UserCookieModel):
    
    is_https = request.url.scheme == "https"
    
   

    response.set_cookie(
        key=settings.PUBLIC_COOKIE_KEY_NAME,
        value=user_cookie.nonce,
        httponly=False,
        secure=is_https,
        samesite="Lax",
        max_age=1 * 24 * 60 * 60  # 1 day
    )

    # save the nonce in the redis
    key = adapter.k(settings.CACHE_AUTH_PREFIX, user_cookie.nonce)

    await adapter.set(
        key=key,
        value={
            "is_valid": True,
            "is_not_valid_since": None,
            "type": "actual/public"
        },
        ex=1 * 24 * 60 * 60  # 1 day
    )

    return response



async def generate_new_nonce_sync(adapter: RedisAdapter) -> str:

    new_nonce = exchange_auth_service.generate_nonce()

    encrypted_nonce = exchange_auth_service.encrypt_new_nonce(new_nonce)

    # save the nonce in the redis
    key = adapter.k(settings.CACHE_AUTH_PREFIX, new_nonce)

    await adapter.set(
        key=key,
        value={
            "is_valid": True,
            "is_not_valid_since": None,
            "type": "temporary/encrypted"
        },
       
    )
    return encrypted_nonce


async def get_user_info_from_redis_sync(adapter: RedisAdapter, session_id: str) -> dict:

    key = adapter.k(settings.CACHE_AUTH_PREFIX, session_id)

    user_info = await adapter.get(key)
    return user_info


async def get_nonce_from_redis_sync(adapter: RedisAdapter, nonce_id: str) -> str:

    key = adapter.k(settings.CACHE_AUTH_PREFIX, nonce_id)

    nonce_info = await adapter.get(key)
    return nonce_info