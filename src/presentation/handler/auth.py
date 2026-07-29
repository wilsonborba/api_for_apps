from fastapi import HTTPException, Security, Request, Response
from fastapi.security.api_key import APIKeyHeader

from src.presentation.handler.exchange_auth_app_handler import get_user_info_from_redis_sync
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
    Verify admin key OR user session.

    User session auth requires:
      - sid cookie (http-only session)
      - csrf cookie + X-CSRF-Token header for mutable requests
    """

    # Admin key path (dev/internal)
    if api_key_secret:
        if api_key_secret == settings.API_KEY_SECRET:
            return api_key_secret
        warning("Invalid API Key; falling back to user authentication flow.")

    adapter = get_redis_adapter(request)

    headers = request.headers
    cookies = request.cookies

    http_only_cookie = cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)  # sid
    csrf_cookie = cookies.get(settings.CSRF_COOKIE_KEY_NAME)

    if not http_only_cookie:
        error(f"Missing session cookie... sid={bool(http_only_cookie)}")
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    user_info = await get_user_info_from_redis_sync(adapter=adapter, session_id=http_only_cookie)
    if not user_info:
        error("Missing user info for session...")
        raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        csrf_header = headers.get("X-CSRF-Token")
        session_csrf = user_info.get("csrf_token")
        if not csrf_cookie or not csrf_header or not session_csrf:
            error(
                "Missing CSRF data...\n"
                f"csrf_cookie={bool(csrf_cookie)} csrf_header={bool(csrf_header)} session_csrf={bool(session_csrf)}"
            )
            raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")
        if csrf_cookie != csrf_header or csrf_cookie != session_csrf:
            error("CSRF token mismatch.")
            raise HTTPException(status_code=403, detail="Missing Authentications Parameters...")

    return True
