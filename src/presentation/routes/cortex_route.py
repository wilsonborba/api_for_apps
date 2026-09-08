"""Public proxy for cortex_api (see GitHub issue #19).

Forwards `/cortex/v1/*` to cortex_api (default http://localhost:8003,
configurable via CORTEX_API_HOST/CORTEX_API_PORT) using the same
LocalProxyService the generic `/apps/{app}/v1/*` proxy uses.

Unlike the generic proxy, this route never requires a login session: the
Cortex Web Chat also serves anonymous/guest usage. Instead it layers a
Client App Attestation check (X-Asodya-App-Proof, see
cortex_attestation_handler.py):

- Valid proof (genuine official Web App request): unlimited usage.
- Missing/invalid proof (external script/cURL/Postman): hard-capped at
  CORTEX_DAILY_TEST_LIMIT requests per UTC calendar day per client IP; the
  next request that day gets HTTP 429.

Every proxied payload also gets its tier/model fields forcibly rewritten to
the cheapest tier (cortex-t0 / tier 0) before forwarding, regardless of what
the client requested, so no paid tier can ever be triggered through this
public-facing route.
"""
from __future__ import annotations

import json
from fnmatch import fnmatchcase
from urllib.parse import urlunsplit

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.core.settings import app_settings
from src.core.utils import get_redis_adapter
from src.core.logs import error
from src.domain.services.local_proxy_service import LocalProxyService
from src.presentation.handler.auth import verify_admin_auth
from src.presentation.handler.cortex_attestation_handler import CORTEX_PROOF_HEADER, verify_app_proof
from src.presentation.handler.user_security_handler import enforce_daily_quota
from src.presentation.handler.responses import MyResponse

cortex_proxy_v1 = APIRouter(prefix="/cortex/v1")
proxy_service = LocalProxyService()

settings = app_settings()

LOG_PROTECTED_PATTERNS = [
    "/logs*",
    "*/logs*",
]


def _is_log_route(path: str) -> bool:
    normalized_path = f"/{path.lstrip('/')}"
    return any(fnmatchcase(normalized_path, pattern) for pattern in LOG_PROTECTED_PATTERNS)

# Hard-locked tier-0 fields. These overwrite whatever the client sent.
TIER0_MODEL = "cortex-t0"
TIER0_TIER = 0
# Fields that could otherwise let a caller escape tier 0 on /execute.
_EXECUTE_ESCAPE_HATCHES = ("force_model", "force_provider", "override_strategy")

CORTEX_SCRIPT_QUOTA_ACTION = "cortex_script_quota"


@cortex_proxy_v1.options("/{path:path}", include_in_schema=False)
async def cortex_proxy_preflight(path: str, request: Request):
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)

    origin = request.headers.get("origin")
    acrm = request.headers.get("access-control-request-method")
    acrh = request.headers.get("access-control-request-headers")

    if not origin:
        origin = urlunsplit((request.url.scheme, request.url.netloc, "", "", ""))

    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = acrm or "GET,POST,PUT,PATCH,DELETE,HEAD,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = (
        acrh or f"Content-Type,Accept,{CORTEX_PROOF_HEADER}"
    )
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Max-Age"] = "600"
    return resp


def sanitize_cortex_payload(path: str, body: bytes) -> bytes:
    """Force tier-0 fields into a cortex_api request body before forwarding.

    Returns the body unchanged if it is empty or not a JSON object (the
    upstream API will reject it on its own terms in that case).
    """
    if not body:
        return body

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body

    if not isinstance(payload, dict):
        return body

    normalized_path = path.strip("/").lower()

    if normalized_path.endswith("chat/completions"):
        payload["model"] = TIER0_MODEL
    elif normalized_path.endswith("execute"):
        payload["tier"] = TIER0_TIER
        for field in _EXECUTE_ESCAPE_HATCHES:
            payload.pop(field, None)
    else:
        # Unknown/future endpoint: defensively hard-lock any tier/model
        # fields it happens to carry, rather than forwarding them as-is.
        if "model" in payload:
            payload["model"] = TIER0_MODEL
        if "tier" in payload:
            payload["tier"] = TIER0_TIER

    return json.dumps(payload).encode("utf-8")


@cortex_proxy_v1.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def cortex_proxy_endpoint(path: str, request: Request, response: Response):
    try:
        if _is_log_route(path):
            await verify_admin_auth(request=request, response=response)
        elif not verify_app_proof(request):
            adapter = get_redis_adapter(request)
            await enforce_daily_quota(
                adapter,
                request=request,
                action=CORTEX_SCRIPT_QUOTA_ACTION,
                limit=settings.CORTEX_DAILY_TEST_LIMIT,
            )

        body_override = None
        if request.method in {"POST", "PUT", "PATCH"}:
            body_override = sanitize_cortex_payload(path, await request.body())

        proxied = await proxy_service.forward_request(
            "cortex", f"/{path}", request, response, body_override=body_override,
        )

        for k, v in response.headers.items():
            if k not in proxied.headers:
                proxied.headers[k] = v

        return proxied
    except HTTPException as e:
        error(f"HTTPException in proxying cortex request: {e.detail}")
        resp = MyResponse(status_code=e.status_code, message=str(e.detail), data=None)
        for k, v in (e.headers or {}).items():
            resp.headers[k] = v
        return resp
    except Exception as e:
        error(f"Error in proxying cortex request: {e}")
        return MyResponse(status_code=400, message="Bad request", data=None)
