"""Client App Attestation for the cortex_api proxy (see cortex_route.py).

The official Web App proves it is the genuine Cortex Web Chat client by
sending an HMAC-SHA256 signature over `f"{date_utc}:{app_id}"`, keyed with a
secret shared only between that frontend build and this backend
(`CORTEX_PROOF_SECRET`, loaded from `.env`). A valid signature bypasses the
strict script/cURL daily quota enforced in cortex_route.py.

This is intentionally separate from `verify_auth`/session cookies: the
cortex proxy also serves anonymous/guest chat, so it cannot require a login
session, only proof of coming from the real client build.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request

from src.core.settings import app_settings

CORTEX_PROOF_HEADER = "X-Asodya-App-Proof"


def _digest(date_utc: str, app_id: str, secret: str) -> str:
    message = f"{date_utc}:{app_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def compute_app_proof(app_id: Optional[str] = None, *, when: Optional[datetime] = None) -> str:
    """Compute the expected proof value for a given day.

    Mirrors what the official Web App computes client-side. Exposed here so
    reference clients and tests can generate a valid header without
    duplicating the HMAC scheme.
    """
    settings = app_settings()
    moment = when or datetime.now(timezone.utc)
    date_utc = moment.strftime("%Y-%m-%d")
    return _digest(date_utc, app_id or settings.CORTEX_APP_ID, settings.CORTEX_PROOF_SECRET)


def verify_app_proof(request: Request) -> bool:
    """Return True only if the request carries a valid X-Asodya-App-Proof.

    Accepts today's or yesterday's UTC date to tolerate clients/servers that
    straddle midnight without granting any meaningful extra window.
    """
    settings = app_settings()
    if not settings.CORTEX_PROOF_SECRET:
        # No secret configured: attestation can never be satisfied, so every
        # request falls back to the strict daily quota. Fail closed.
        return False

    provided = request.headers.get(CORTEX_PROOF_HEADER)
    if not provided:
        return False

    now = datetime.now(timezone.utc)
    for moment in (now, now - timedelta(days=1)):
        expected = compute_app_proof(when=moment)
        if hmac.compare_digest(provided, expected):
            return True
    return False
