# src/routes/proxy_router.py
from fastapi import APIRouter, Request, Response, status, Depends
from src.core.settings import app_settings
from src.domain.services.local_proxy_service import LocalProxyService
from src.presentation.handler.responses import MyResponse
from src.core.logs import error
from urllib.parse import urlunsplit
from src.presentation.handler.auth import verify_auth

apps_proxy_v1 = APIRouter(prefix="/{app}/v1")
proxy_service = LocalProxyService()

settings = app_settings()

@apps_proxy_v1.options("/{path:path}", include_in_schema=False)
async def proxy_preflight(app: str, path: str, request: Request):
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)

    origin = request.headers.get("origin")
    acrm   = request.headers.get("access-control-request-method")
    acrh   = request.headers.get("access-control-request-headers")

    # Mirror Origin if provided; else fall back to our own origin
    if not origin:
        origin = urlunsplit((request.url.scheme, request.url.netloc, "", "", ""))

    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"

    # Methods & headers: echo if provided; else a safe superset
    resp.headers["Access-Control-Allow-Methods"] = acrm or "GET,POST,PUT,PATCH,DELETE,HEAD,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = acrh or "Authorization,Content-Type,Accept"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Max-Age"] = "600"
    
    # Optional but handy for Swagger to read custom headers
    resp.headers["Access-Control-Expose-Headers"] = "X-Proxy-Target-Url"
    
    return resp

@apps_proxy_v1.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def proxy_endpoint(app: str, path: str, request: Request, response: Response, api_key_secret: str = Depends(verify_auth)):
    try:
        proxied = await proxy_service.forward_request(app, f"/{path}", request)

        # IMPORTANT: copy headers set by dependencies (e.g., NEXT_AUTH_NONCE) onto the proxied response
        # (they would otherwise be dropped because StreamingResponse bypasses the injected Response)
        for k, v in response.headers.items():
            # don't clobber upstream headers unless it's your own nonce header
            if k.lower() == settings.NEXT_AUTH_NONCE_HEADER_KEY_NAME.lower() or k not in proxied.headers:
                proxied.headers[k] = v

        return proxied
    except Exception as e:
        error(f"Error in proxying request: {e}")
        return MyResponse(status_code=400, message="Bad request", data=None)
