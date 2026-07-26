from fastapi import Request
from src.dal.local.redis_adapter import RedisAdapter
from src.domain.models.user_model import UserCookieModel
from src.core.settings import app_settings
from src.presentation.handler.responses import ExchangeAuthError
from src.domain.services.exchange_auth_app_service import ExchangeAuthService

exchange_auth_service = ExchangeAuthService()
settings = app_settings()


def exchange_auth_sync(auth_exchange_token: str) -> UserCookieModel:
    auth_exchange_payload = exchange_auth_service.decrypt_auth_exchange_token(
        auth_exchange_token
    )
    is_valid, error_message = exchange_auth_service.validate_auth_exchange_payload(
        auth_exchange_payload
    )

    if not is_valid:
        raise ExchangeAuthError(error_message)

    user_cookie = exchange_auth_service.build_user_cookie(auth_exchange_payload)
    return user_cookie


def is_request_https(request: Request) -> bool:
    """
    Correct HTTPS detection behind Cloudflare Tunnel / reverse proxies.
    Cloudflare terminates TLS and forwards to your origin; the origin may see http,
    but X-Forwarded-Proto should be 'https'.
    """
    xf_proto = request.headers.get("x-forwarded-proto")
    if xf_proto:
        return xf_proto.lower() == "https"
    return request.url.scheme == "https"


def cookie_domain_for_asodya() -> str:
    """
    Allows sharing cookies across auth.asodya.com and api.asodya.com.
    If you don't want that behavior, return None and do not pass 'domain'.
    """
    return ".asodya.com"


async def set_http_only_cookies_for_auth_sync(
    adapter: RedisAdapter,
    request: Request,
    response,
    user_cookie: UserCookieModel
):
    """
    The user_cookie.session_id is stored in Redis and used to lookup user info.
    """
    https_external = is_request_https(request)

    # For cross-site XHR/fetch cookie auth:
    # SameSite=None requires Secure=True (browser rule).
    # If you are calling via https://api.asodya.com, this must end up True.
    response.set_cookie(
        key=settings.HTTP_ONLY_COOKIE_KEY_NAME,
        value=user_cookie.session_id,
        httponly=True,
        secure=True if https_external else False,
        samesite="none",
        max_age=1 * 24 * 60 * 60 + 1 * 60 * 60,  # 1 day + 1 hour
        path="/",
        domain=cookie_domain_for_asodya(),
    )

    # Save session in Redis
    key = adapter.k(settings.CACHE_AUTH_PREFIX, user_cookie.session_id)
    await adapter.set(
        key=key,
        value=user_cookie.to_dict(),
        ex=1 * 24 * 60 * 60 + 1 * 60 * 60,
    )

    return response


async def set_public_cookies_for_auth_sync(
    adapter: RedisAdapter,
    request: Request,
    response,
    user_cookie: UserCookieModel
):
    https_external = is_request_https(request)

    response.set_cookie(
        key=settings.PUBLIC_COOKIE_KEY_NAME,
        value=user_cookie.nonce,
        httponly=False,
        secure=True if https_external else False,
        samesite="none",
        max_age=1 * 24 * 60 * 60,  # 1 day
        path="/",
        domain=cookie_domain_for_asodya(),
    )

    # Save nonce in Redis
    key = adapter.k(settings.CACHE_AUTH_PREFIX, user_cookie.nonce)
    await adapter.set(
        key=key,
        value={
            "is_valid": True,
            "is_not_valid_since": None,
            "type": "actual/public",
        },
        ex=1 * 24 * 60 * 60,
    )

    return response


async def generate_new_nonce_sync(adapter: RedisAdapter) -> str:
    new_nonce = exchange_auth_service.generate_nonce()
    encrypted_nonce = exchange_auth_service.encrypt_new_nonce(new_nonce)

    key = adapter.k(settings.CACHE_AUTH_PREFIX, new_nonce)
    await adapter.set(
        key=key,
        value={
            "is_valid": True,
            "is_not_valid_since": None,
            "type": "temporary/encrypted",
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
