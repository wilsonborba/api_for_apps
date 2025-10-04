



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


def set_http_only_cookies_for_auth_sync(response, user_cookie: UserCookieModel):
    """The user_cookie is a session_id key generated that will be queryed in redis to get user info"""

    # prepare user_cookie transformed json

    

    response.set_cookie(
        key=settings.HTTP_ONLY_COOKIE_KEY_NAME,
        value=user_cookie.session_id,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=1 * 24 * 60 * 60 + 1 * 60 * 60  # 1 day and 1 hour
    )

    return response

def set_public_cookies_for_auth_sync(response, user_cookie: UserCookieModel):
    response.set_cookie(
        key=settings.PUBLIC_COOKIE_KEY_NAME,
        value=user_cookie.nonce,
        httponly=False,
        secure=True,
        samesite="Lax",
        max_age=1 * 24 * 60 * 60  # 1 day
    )

    return response


def save_on_redis_sync(adapter: RedisAdapter, user_cookie: UserCookieModel) -> bool:

    # adapter.set(
    #     key=user_cookie.session_id,
    #     value=user_cookie.to_dict(),
    #     ex=1 * 24 * 60 * 60 + 1 * 60 * 60  # 1 day and 1 hour
    # )

    return adapter.set(
        key=user_cookie.session_id,
        value=user_cookie.to_dict(),
        ex=1 * 24 * 60 * 60 + 1 * 60 * 60  # 1 day and 1 hour
    )



def get_user_info_from_redis_sync(adapter: RedisAdapter, session_id: str) -> dict:
    user_info = adapter.get(session_id)
    return user_info


def get_nonce_from_redis_sync(adapter: RedisAdapter, nonce_id: str) -> str:
    
    nonce_info = adapter.get(nonce_id)
    return nonce_info