import time
from fastapi import HTTPException, Security, Request, Response
from fastapi.security.api_key import APIKeyHeader

from src.presentation.handler.exchange_auth_app_handler import (
    generate_new_nonce_sync,
    get_nonce_from_redis_sync,
    get_user_info_from_redis_sync,
)
from src.core.utils import get_redis_adapter
from src.core.settings import app_settings
from src.core.logs import error, warning

settings = app_settings()

api_admin_key_header = APIKeyHeader(name=settings.API_ADMIN_KEY_NAME, auto_error=False)


async def verify_auth(
    request: Request,
    response: Response,
    api_key_secret: str = Security(api_admin_key_header),
):
    """
    Verify admin key OR (cookie session + nonce headers/cookies).

    Required for user auth:
      - sid cookie (http-only session)
      - temporary nonce (T-A-N header)
      - actual nonce: prefer A-A-N header, fallback to hint cookie
    """

    # Admin key path (dev/internal)
    if api_key_secret:
        if api_key_secret == settings.API_KEY_SECRET:
            return api_key_secret
        warning("Invalid API Key; falling back to user authentication flow.")

    adapter = get_redis_adapter(request)

    headers = request.headers
    cookies = request.cookies

    # Cookies
    http_only_cookie = cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)  # sid
    public_cookie = cookies.get(settings.PUBLIC_COOKIE_KEY_NAME)        # hint

    if not http_only_cookie or not public_cookie:
        error(f"Missing Cookies... sid={bool(http_only_cookie)} hint={bool(public_cookie)}")
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    # Nonce headers
    actual_nonce_headers = headers.get(settings.ACTUAL_AUTH_NONCE_HEADER_KEY_NAME)      # A-A-N
    temporary_nonce_headers = headers.get(settings.TEMPORARY_AUTH_NONCE_HEADER_KEY_NAME)  # T-A-N

    # Fallback: if A-A-N not sent, use hint cookie as "actual nonce"
    actual_nonce = actual_nonce_headers or public_cookie
    temporary_nonce = temporary_nonce_headers

    if not temporary_nonce:
        error(f"Missing temporary nonce header: {settings.TEMPORARY_AUTH_NONCE_HEADER_KEY_NAME} (T-A-N)")
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    # Load user info from session
    user_info = await get_user_info_from_redis_sync(adapter=adapter, session_id=http_only_cookie)
    if not user_info:
        error("Missing user info for session...")
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    # Redis checks
    actual_nonce_redis = await get_nonce_from_redis_sync(adapter, actual_nonce)
    temporary_nonce_redis = await get_nonce_from_redis_sync(adapter, temporary_nonce)

    if not actual_nonce_redis or not temporary_nonce_redis:
        error(
            "Missing/Not Found Nonce in Redis...\n"
            f"actual_nonce: {actual_nonce}\nactual_nonce_redis: {actual_nonce_redis}\n"
            f"temporary_nonce: {temporary_nonce}\ntemporary_nonce_redis: {temporary_nonce_redis}"
        )
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    # Temporary nonce validity / grace period logic (kept as-is)
    is_valid_temporary_nonce = temporary_nonce_redis.get("is_valid", False)

    if not is_valid_temporary_nonce:
        is_not_valid_since = int(temporary_nonce_redis.get("is_not_valid_since") or 0)
        int_time_now = int(time.time())

        if (int_time_now - is_not_valid_since > 30):
            error(f"Expired Nonce... {is_not_valid_since} - {int_time_now} > 30")
            raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

        warning("The nonce is not valid, but still in grace period...")

        # Verify user nonce matches the “actual nonce” you received
        user_nonce_id = user_info.get("nonce", None)
        if actual_nonce != user_nonce_id:
            error("Invalid Nonce...")
            raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    # Rotate nonce: generate new temporary nonce and send it back
    new_nonce = await generate_new_nonce_sync(adapter)
    response.headers[settings.NEXT_AUTH_NONCE_HEADER_KEY_NAME] = new_nonce

    # Invalidate old temporary nonce and store for 5 minutes
    temporary_nonce_redis["is_valid"] = False
    temporary_nonce_redis["is_not_valid_since"] = int(time.time())

    key = adapter.k(settings.CACHE_AUTH_PREFIX, temporary_nonce)
    await adapter.set(key=key, value=temporary_nonce_redis, ex=5 * 60)

    return True
