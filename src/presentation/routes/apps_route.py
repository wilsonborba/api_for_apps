# src/routes/proxy_router.py
from urllib.parse import urlunsplit
from fastapi import APIRouter, HTTPException, Request, Response, status
from fnmatch import fnmatchcase
from src.presentation.handler.exchange_auth_app_handler import get_user_info_from_redis_sync
from src.core.utils import get_redis_adapter
from src.core.settings import app_settings
from src.domain.services.local_proxy_service import LocalProxyService
from src.presentation.handler.auth import ADMIN_ACCESS_LEVEL, verify_admin_auth, verify_auth
from src.core.logs import error, warning
from src.presentation.handler.responses import MyResponse

apps_proxy_v1 = APIRouter(prefix="/{app}/v1")
proxy_service = LocalProxyService()

settings = app_settings()

LOG_PROTECTED_PATTERNS = [
    "/logs*",
    "*/logs*",
]


def _is_log_route(path: str) -> bool:
    normalized_path = f"/{path.lstrip('/')}"
    return any(fnmatchcase(normalized_path, pattern) for pattern in LOG_PROTECTED_PATTERNS)

@apps_proxy_v1.options("/{path:path}", include_in_schema=False)
async def proxy_preflight(app: str, path: str, request: Request):
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)

    origin = request.headers.get("origin")
    acrm = request.headers.get("access-control-request-method")
    acrh = request.headers.get("access-control-request-headers")

    # Mirror Origin if provided; else fall back to our own origin
    if not origin:
        origin = urlunsplit((request.url.scheme, request.url.netloc, "", "", ""))

    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"

    # Methods & headers: echo if provided; else a safe superset
    resp.headers["Access-Control-Allow-Methods"] = (
        acrm or "GET,POST,PUT,PATCH,DELETE,HEAD,OPTIONS"
    )
    resp.headers["Access-Control-Allow-Headers"] = (
        acrh or "Authorization,Content-Type,Accept,X-CSRF-Token,X-CSRFToken"
    )
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Max-Age"] = "600"

    # Optional but handy for Swagger to read custom headers
    resp.headers["Access-Control-Expose-Headers"] = "X-Proxy-Target-Url"

    return resp

def _is_public_proxy_request(app: str, path: str, method: str) -> bool:
    normalized_app = app.strip().lower().replace("/", "")
    normalized_path = f"/{path.lstrip('/')}"
    method_patterns = settings.PUBLIC_PROXY_ROUTES.get(normalized_app, {})
    allowlist = method_patterns.get(method.upper(), [])
    return any(fnmatchcase(normalized_path, pattern) for pattern in allowlist)


@apps_proxy_v1.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def proxy_endpoint(app: str, path: str, request: Request, response: Response):
    try:
        internal_headers = None
        if _is_log_route(path):
            await verify_admin_auth(request=request, response=response)
        elif not _is_public_proxy_request(app, path, request.method):
            await verify_auth(request=request, response=response)
            user_session_id = request.cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)

            adapter = get_redis_adapter(request)

            user_info = await get_user_info_from_redis_sync(adapter=adapter, session_id=user_session_id)
            if not user_info or not user_info.get("user_uuid_id"):
                raise ValueError("Authenticated session is missing identity")
            internal_headers = {"x-uuid": user_info["user_uuid_id"]}

        proxied = await proxy_service.forward_request(
            app, f"/{path}", request, response, internal_headers=internal_headers
        )

        # IMPORTANT: copy headers set by dependencies (e.g., NEXT_AUTH_NONCE) onto the proxied response
        # (they would otherwise be dropped because StreamingResponse bypasses the injected Response)
        for k, v in response.headers.items():
            if k not in proxied.headers:
                proxied.headers[k] = v

        # remove back for security the x-uuid header

        if "x-uuid" in proxied.headers:
            warning("Removing x-uuid header from proxied response for security.")
            del proxied.headers["x-uuid"]

        return proxied
    except HTTPException as e:
        error(f"HTTPException in proxying request: {e.detail}")
        return MyResponse(status_code=e.status_code, message=str(e.detail), data=None)
    except Exception as e:
        error(f"Error in proxying request: {e}")
        return MyResponse(status_code=400, message="Bad request", data=None)
