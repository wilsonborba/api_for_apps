from fastapi import Request
from src.dal.local.redis_adapter import RedisAdapter
from src.domain.models.user_model import UserCookieModel
from src.core.settings import app_settings
from src.presentation.handler.responses import ExchangeAuthError
from src.domain.services.exchange_auth_app_service import ExchangeAuthService

exchange_auth_service = ExchangeAuthService()
settings = app_settings()


async def register_auth_exchange_artifact(
    adapter: RedisAdapter, auth_exchange_token: str
) -> None:
    """Record a freshly issued artifact so only this API can redeem it once."""
    auth_exchange_payload = exchange_auth_service.decrypt_auth_exchange_token(
        auth_exchange_token
    )
    is_valid, error_message = exchange_auth_service.validate_auth_exchange_payload(
        auth_exchange_payload
    )

    if not is_valid:
        raise ExchangeAuthError(error_message)

    key = adapter.k(settings.EXCHANGE_ARTIFACT_PREFIX, auth_exchange_payload["jti"])
    stored = await adapter.set(
        key,
        {"app": auth_exchange_payload["app"]},
        ex=settings.EXCHANGE_ARTIFACT_TTL_SECONDS,
        nx=True,
    )
    if not stored:
        raise ExchangeAuthError("Could not issue exchange artifact")


async def exchange_auth_sync(
    adapter: RedisAdapter, auth_exchange_token: str, expected_app: str | None = None
) -> UserCookieModel:
    auth_exchange_payload = exchange_auth_service.decrypt_auth_exchange_token(
        auth_exchange_token
    )
    is_valid, error_message = exchange_auth_service.validate_auth_exchange_payload(
        auth_exchange_payload
    )
    if not is_valid:
        raise ExchangeAuthError(error_message)

    app = auth_exchange_payload["app"]
    if expected_app and app != expected_app:
        raise ExchangeAuthError("Exchange artifact is for a different application")

    key = adapter.k(settings.EXCHANGE_ARTIFACT_PREFIX, auth_exchange_payload["jti"])
    artifact = await adapter.getdel(key)
    if artifact is None or artifact.get("app") != app:
        raise ExchangeAuthError("Exchange artifact is invalid, expired, or already used")

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


def resolve_cookie_domain(request: Request) -> str | None:
    """
    Decides the cookie `Domain` attribute per request instead of a static
    dev/prod flag, so the same always-on instance behaves correctly whether
    it's reached through the real domain (Cloudflare Tunnel) or directly by
    LAN IP for local testing.

    A `Domain=.asodya.com` cookie is only valid for requests whose host is
    actually a subdomain of asodya.com; setting it for a bare LAN IP makes
    the browser silently reject the whole Set-Cookie header. So: real
    subdomain -> shared prod domain (needed so sibling apps like cortex/
    certifications can read it); anything else (LAN IP, localhost) -> no
    Domain attribute at all (host-only cookie, scoped to that literal host).
    """
    host = (request.headers.get("x-forwarded-host") or request.url.hostname or "").lower()
    if host.endswith(settings.ASODYA_MAIN_DOMAIN):
        return settings.COOKIE_DOMAIN_PROD
    return None


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

    response.set_cookie(
        key=settings.HTTP_ONLY_COOKIE_KEY_NAME,
        value=user_cookie.session_id,
        httponly=True,
        secure=True if https_external else False,
        samesite="lax",
        max_age=settings.SESSION_TTL_SECONDS,
        path="/",
        domain=resolve_cookie_domain(request),
    )

    # Save session in Redis
    key = adapter.k(settings.CACHE_AUTH_PREFIX, user_cookie.session_id)
    await adapter.set(
        key=key,
        value=user_cookie.to_dict(),
        ex=settings.SESSION_TTL_SECONDS,
    )

    return response


async def set_csrf_cookie_for_auth_sync(request: Request, response, user_cookie: UserCookieModel):
    https_external = is_request_https(request)
    response.set_cookie(
        key=settings.CSRF_COOKIE_KEY_NAME,
        value=user_cookie.csrf_token,
        httponly=False,
        secure=True if https_external else False,
        samesite="lax",
        max_age=settings.CSRF_TTL_SECONDS,
        path="/",
        domain=resolve_cookie_domain(request),
    )
    return response


async def get_user_info_from_redis_sync(adapter: RedisAdapter, session_id: str) -> dict:
    key = adapter.k(settings.CACHE_AUTH_PREFIX, session_id)
    user_info = await adapter.get(key)
    return user_info
