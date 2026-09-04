from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterable, Tuple, Optional
from fastapi import Request, HTTPException

from src.dal.local.redis_adapter import RedisAdapter
from src.core.logs import warning

SECONDS_PER_DAY = 24 * 60 * 60


# ---------------------------
# Helpers
# ---------------------------

def get_client_ip(request: Request) -> str:
    """
    Extracts client IP.
    If behind proxy/ingress, uses the first from X-Forwarded-For.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host


def norm_user_email(user_email: Optional[str]) -> str:
    return (user_email or "").strip().lower()


# ---------------------------
# Rate limiting: fixed window
# ---------------------------

async def _incr_with_ttl(adapter: RedisAdapter, key: str, window: int) -> int:
    """
    INCR with fixed TTL: sets TTL only when key is first created.
    Returns the current count in the window.
    """
    count = await adapter.incr(key, amount=1)
    if count == 1:
        await adapter.expire(key, window)
    return count


async def enforce_ip_rate(
    adapter: RedisAdapter,
    *,
    request: Request,
    action: str,                    # e.g. "login" | "signup"
    limits: Iterable[Tuple[int,int]] = ((5, 60), (20, 3600)),
    namespace: str = "rl:ip",
) -> None:
    """
    Enforces multiple rate limits by IP for an action.
    limits = [(times, window_sec), ...]
    Example: [(5, 60), (20, 3600)]
    """
    ip = get_client_ip(request)
    for times, window in limits:
        key = adapter.k(namespace, action, f"ip:{ip}", f"{window}s")
        current = await _incr_with_ttl(adapter, key, window)
        if current > times:
            warning(f"Rate limit exceeded: {key} ({current} > {times})")
            raise HTTPException(
                status_code=429,
                detail=f"Too many {action} attempts. Try again later.",
            )


async def enforce_username_rate(
    adapter: RedisAdapter,
    *,
    action: str,
    user_email: str,
    limits: Iterable[Tuple[int,int]] = ((3, 60), (10, 600)),
    namespace: str = "rl:user",
) -> None:
    """
    Enforces multiple rate limits by username.
    Helps prevent hammering one account.
    """
    u = norm_user_email(user_email)
    if not u:
        return
    for times, window in limits:
        key = adapter.k(namespace, action, f"user:{u}", f"{window}s")
        current = await _incr_with_ttl(adapter, key, window)
        if current > times:
            warning(f"Rate limit exceeded: {key} ({current} > {times})")
            raise HTTPException(
                status_code=429,
                detail=f"Too many {action} attempts for this user_email. Try again later.",
            )


# ---------------------------
# Rate limiting: strict calendar-day cap
# ---------------------------

async def enforce_daily_quota(
    adapter: RedisAdapter,
    *,
    request: Request,
    action: str,
    limit: int,
    namespace: str = "rl:daily",
) -> None:
    """
    Caps an action at `limit` requests per UTC calendar day, per client IP.
    Used by the cortex proxy to strictly limit unattested (external
    script/cURL) traffic while a valid X-Asodya-App-Proof bypasses this
    check entirely. Raises HTTP 429 on the (limit + 1)th request of the day.
    """
    ip = get_client_ip(request)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = adapter.k(namespace, action, f"ip:{ip}", today)
    current = await _incr_with_ttl(adapter, key, SECONDS_PER_DAY)
    if current > limit:
        warning(f"Daily quota exceeded: {key} ({current} > {limit})")
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily test limit of {limit} requests reached for direct "
                "script access. Use the official Web App for unlimited "
                "usage, or try again after the daily window resets."
            ),
            headers={"Retry-After": str(SECONDS_PER_DAY)},
        )


# ---------------------------
# Fail lock after repeated failures
# ---------------------------

async def enforce_fail_lock(
    adapter: RedisAdapter,
    *,
    request: Request,
    user_email: str,
    success: bool,
    max_failures: int = 5,
    lock_seconds: int = 600,        # 10 minutes
    fail_window: int = 900,         # 15 minutes
    namespace: str = "lock:login",
) -> None:
    """
    Tracks failed attempts by (IP+username). If failures exceed
    max_failures within fail_window, sets a lock key (with TTL = lock_seconds)
    and blocks further attempts.
    """
    ip = get_client_ip(request)
    u = norm_user_email(user_email)

    lock_key = adapter.k(namespace, f"user:{u}", f"ip:{ip}", "active")
    ttl = await adapter.ttl(lock_key)
    if ttl and ttl > 0:
        warning(f"Account locked: {lock_key} (ttl={ttl})")
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Temporarily locked. Try again later.",
        )

    if success:
        # Reset failure counter
        fail_key = adapter.k("fail:login", f"user:{u}", f"ip:{ip}")
        await adapter.delete(fail_key)
        return

    # Failure: increment
    fail_key = adapter.k("fail:login", f"user:{u}", f"ip:{ip}")
    count = await _incr_with_ttl(adapter, fail_key, fail_window)
    if count >= max_failures:
        await adapter.set(lock_key, "1", ex=lock_seconds, nx=True)
        warning(f"Account locked due to failures: {lock_key} (ttl={lock_seconds})")
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Temporarily locked. Try again later.",
        )


# ---------------------------
# Optional progressive backoff
# ---------------------------

async def progressive_backoff_delay_ms(
    adapter: RedisAdapter,
    *,
    request: Request,
    user_email: str,
    base_ms: int = 150,
    max_ms: int = 1000,
    namespace: str = "backoff:login",
) -> int:
    """
    Returns a suggested artificial delay (in ms) to slow down brute force.
    Increases with repeated attempts within a short window.
    Does not block, only suggests delay for asyncio.sleep.
    """
    import math

    ip = get_client_ip(request)
    u = norm_user_email(user_email)
    key = adapter.k(namespace, f"user:{u}", f"ip:{ip}")

    count = await _incr_with_ttl(adapter, key, window=60)  # 1-minute window
    delay = int(min(max_ms, base_ms * math.log2(count + 1)))
    warning(f"Suggested backoff delay: {delay} ms for key: {key} (count={count})")
    return delay
