from __future__ import annotations

import asyncio
import re

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from src.core.logs import error
from src.core.settings import app_settings
from src.core.utils import get_redis_adapter
from src.dal.remote.supabase_auth_adapter import SupabaseAuthAdapter
from src.domain.services.local_proxy_service import LocalProxyService
from src.presentation.handler.responses import MyResponse
from src.presentation.handler.user_security_handler import (
    enforce_ip_rate,
    enforce_username_rate,
    progressive_backoff_delay_ms,
)


waitlist_router = APIRouter(prefix="/apps/certifications/v1")
_proxy = LocalProxyService()
_supabase = SupabaseAuthAdapter()
_settings = app_settings()


class WaitlistRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    plan: str = Field(default="free", pattern="^free$")


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise HTTPException(status_code=422, detail="Invalid waitlist request")
    return normalized


async def _rate_limit(request: Request, email: str) -> None:
    adapter = get_redis_adapter(request)
    await enforce_ip_rate(
        adapter,
        request=request,
        action="waitlist",
        limits=((5, 60), (20, 3600)),
    )
    await enforce_username_rate(
        adapter,
        action="waitlist",
        user_email=email,
        limits=((3, 60), (10, 600)),
    )
    delay_ms = await progressive_backoff_delay_ms(
        adapter,
        request=request,
        user_email=email,
        namespace="backoff:waitlist",
    )
    await asyncio.sleep(delay_ms / 1000.0)


@waitlist_router.post("/waitlist", status_code=status.HTTP_202_ACCEPTED)
async def join_waitlist(
    payload: WaitlistRequest,
    request: Request,
    response: Response,
):
    """Public waitlist entrypoint with a service-authenticated app call."""
    email = _normalize_email(payload.email)
    try:
        await _rate_limit(request, email)
        registered = await asyncio.to_thread(_supabase.user_exists_by_email, email)
        return await _proxy.forward_request(
            "certifications",
            "/waitlist",
            request,
            response,
            internal_headers={
                "x-certifications-service-key": _settings.CERTIFICATIONS_SERVICE_KEY,
                "x-certifications-waitlist-registered": str(registered).lower(),
            },
        )
    except HTTPException as exc:
        error(f"Waitlist request rejected: status={exc.status_code}")
        return MyResponse(
            status_code=exc.status_code,
            message="Request could not be completed. Please try again later.",
            data=None,
        )
    except httpx.HTTPError as exc:
        error(f"Waitlist provider request failed: {type(exc).__name__}")
        return MyResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="Waitlist is temporarily unavailable. Please try again later.",
            data=None,
        )
    except Exception as exc:
        error(f"Waitlist gateway request failed: {type(exc).__name__}")
        return MyResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="Waitlist is temporarily unavailable. Please try again later.",
            data=None,
        )
