from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from src.core.logs import error, warning
from src.core.settings import app_settings
from src.core.utils import get_redis_adapter
from src.dal.local.redis_adapter import RedisAdapter
from src.domain.models.telemetry_model import ClientErrorPayload
from src.domain.services.telemetry_service import TelemetryService
from src.presentation.handler.auth import verify_admin_auth, verify_auth
from src.presentation.handler.exchange_auth_app_handler import get_user_info_from_redis_sync

telemetry_router = APIRouter(prefix="/telemetry/v1")
telemetry_service = TelemetryService()
settings = app_settings()


def _get_client_ip(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


import re

def _is_allowed_telemetry_origin(request: Request) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        # Non-browser clients or direct internal calls without origin header
        return True
    
    origin_lower = origin.lower()
    # Allowed domains
    if ".asodya.com" in origin_lower or origin_lower.startswith("https://asodya.com"):
        return True
    # Allowed localhost / local dev LAN regex
    if re.search(r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|172\.\d+\.\d+\.\d+|100\.\d+\.\d+\.\d+)(:\d+)?", origin_lower):
        return True
    return False


@telemetry_router.post(
    "/client-errors",
    summary="Ingest frontend client error reports",
    description="Accepts client error telemetry, rate-limited per IP, stored in CouchDB.",
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_client_error(
    request: Request,
    payload: ClientErrorPayload,
    background_tasks: BackgroundTasks,
    redis: RedisAdapter = Depends(get_redis_adapter),
):
    if not _is_allowed_telemetry_origin(request):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"message": "Forbidden origin.", "data": None},
        )

    client_ip = _get_client_ip(request)

    # Redis rate-limiting (10 requests per minute per IP)
    allowed = await telemetry_service.check_rate_limit(redis, client_ip, limit=10, window_seconds=60)
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"message": "Rate limit exceeded. Try again later.", "data": None},
        )

    # Extract session / user information if available in cookie
    session_id = request.cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)
    user_id = None
    if session_id:
        try:
            user_info = await get_user_info_from_redis_sync(adapter=redis, session_id=session_id)
            if user_info and isinstance(user_info, dict):
                user_id = user_info.get("id") or user_info.get("user_id")
        except Exception:
            pass

    user_agent = request.headers.get("user-agent")

    # Fire-and-forget in background to return 202 Accepted immediately
    background_tasks.add_task(
        telemetry_service.record_client_error,
        payload=payload,
        ip_address=client_ip,
        user_agent=user_agent,
        session_id=session_id,
        user_id=user_id,
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"message": "Telemetry accepted.", "data": {"status": "queued"}},
    )


@telemetry_router.get(
    "/client-errors",
    summary="Query recent client errors (Admin only)",
    description="Lists recent client-side errors from CouchDB.",
    dependencies=[Depends(verify_admin_auth)],
)
async def list_client_errors(
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
):
    try:
        errors = telemetry_service.list_errors(limit=limit, skip=skip)
        return {"message": "Success", "data": {"total": len(errors), "errors": errors}}
    except Exception as exc:
        error(f"Failed to query client errors: {exc}")
        raise HTTPException(status_code=500, detail="Failed to retrieve errors")
