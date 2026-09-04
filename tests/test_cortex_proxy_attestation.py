from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("API_KEY_SECRET", "test-admin-key")
os.environ.setdefault("DEFAULT_DB_HOST", "localhost")
os.environ.setdefault("DEFAULT_DB_PORT", "5432")
os.environ.setdefault("DEFAULT_DB_USER", "test")
os.environ.setdefault("DEFAULT_DB_PASSWORD", "test")
os.environ.setdefault("DEFAULT_DB_NAME", "test")
os.environ.setdefault("FERNET_KEY_SECRET", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("SERVER_FERNET_KEY_SECRET", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-supabase-secret")
os.environ.setdefault("CERTIFICATIONS_SERVICE_KEY", "test-certifications-key")
os.environ.setdefault("CORTEX_PROOF_SECRET", "test-cortex-proof-secret")

from fastapi import HTTPException, Response

from src.core.settings import app_settings
from src.domain.services.local_proxy_service import LocalProxyService
from src.presentation.handler.cortex_attestation_handler import (
    CORTEX_PROOF_HEADER,
    compute_app_proof,
    verify_app_proof,
)
from src.presentation.handler.user_security_handler import enforce_daily_quota
from src.presentation.routes import cortex_route
from src.presentation.routes.cortex_route import (
    TIER0_MODEL,
    TIER0_TIER,
    cortex_proxy_endpoint,
    sanitize_cortex_payload,
)

# app_settings() is process-wide memoized (lru_cache), and whichever test
# module imports first (alphabetically before this one) may already have
# instantiated it before CORTEX_PROOF_SECRET's os.environ.setdefault above
# took effect. Set it directly on the cached singleton so attestation tests
# in this file have a deterministic, non-empty secret to sign/verify with.
app_settings().CORTEX_PROOF_SECRET = "test-cortex-proof-secret"


class _Headers(dict):
    def get(self, key, default=None):  # header lookups are case-insensitive in practice
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _Request:
    method = "POST"
    client = type("Client", (), {"host": "203.0.113.7"})()

    def __init__(self, headers=None, body: bytes = b"{}"):
        self.headers = _Headers(headers or {})
        self._body = body

    async def body(self) -> bytes:
        return self._body


class FakeRedisAdapter:
    """Minimal in-memory stand-in for RedisAdapter's rate-limit surface.

    Never touches a real Redis instance: enforce_daily_quota only calls
    `.k()`, `.incr()` and `.expire()`, all reproduced here in-process.
    """

    def __init__(self):
        self._counters: dict[str, int] = {}

    def k(self, *parts) -> str:
        return ":".join(str(p) for p in parts if p is not None and str(p) != "")

    async def incr(self, key: str, amount: int = 1) -> int:
        self._counters[key] = self._counters.get(key, 0) + amount
        return self._counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class CortexPortMappingTests(unittest.TestCase):
    def test_cortex_app_is_mapped_to_its_configured_port(self) -> None:
        service = LocalProxyService()
        self.assertEqual(service.get_port("cortex"), app_settings().CORTEX_API_PORT)


class CortexPayloadSanitizationTests(unittest.TestCase):
    def test_chat_completions_model_is_forced_to_tier0(self) -> None:
        body = b'{"model":"gpt-4-turbo","messages":[{"role":"user","content":"hi"}]}'
        sanitized = sanitize_cortex_payload("chat/completions", body)
        self.assertEqual(sanitized, (
            b'{"model": "' + TIER0_MODEL.encode() + b'", "messages": [{"role": "user", "content": "hi"}]}'
        ))

    def test_execute_tier_and_escape_hatches_are_stripped(self) -> None:
        body = (
            b'{"prompt":"hi","tier":5,"force_model":"gpt-4","force_provider":"openai",'
            b'"override_strategy":"expensive"}'
        )
        sanitized = sanitize_cortex_payload("execute", body)
        import json

        payload = json.loads(sanitized)
        self.assertEqual(payload["tier"], TIER0_TIER)
        self.assertNotIn("force_model", payload)
        self.assertNotIn("force_provider", payload)
        self.assertNotIn("override_strategy", payload)

    def test_non_json_body_is_forwarded_unchanged(self) -> None:
        body = b"not json"
        self.assertEqual(sanitize_cortex_payload("execute", body), body)

    def test_empty_body_is_forwarded_unchanged(self) -> None:
        self.assertEqual(sanitize_cortex_payload("execute", b""), b"")


class CortexAttestationTests(unittest.TestCase):
    def test_valid_proof_from_official_web_app_verifies(self) -> None:
        request = _Request(headers={CORTEX_PROOF_HEADER: compute_app_proof()})
        self.assertTrue(verify_app_proof(request))

    def test_missing_header_fails(self) -> None:
        request = _Request(headers={})
        self.assertFalse(verify_app_proof(request))

    def test_wrong_signature_fails(self) -> None:
        request = _Request(headers={CORTEX_PROOF_HEADER: "not-the-real-signature"})
        self.assertFalse(verify_app_proof(request))

    def test_yesterdays_signature_is_still_accepted_for_clock_skew(self) -> None:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        request = _Request(headers={CORTEX_PROOF_HEADER: compute_app_proof(when=yesterday)})
        self.assertTrue(verify_app_proof(request))

    def test_no_secret_configured_fails_closed(self) -> None:
        with patch.object(app_settings(), "CORTEX_PROOF_SECRET", ""):
            request = _Request(headers={CORTEX_PROOF_HEADER: compute_app_proof()})
            self.assertFalse(verify_app_proof(request))


class CortexDailyQuotaTests(unittest.TestCase):
    def test_sixth_request_in_a_day_is_rejected_with_429(self) -> None:
        adapter = FakeRedisAdapter()
        request = _Request(headers={})

        async def run():
            for _ in range(5):
                await enforce_daily_quota(
                    adapter, request=request, action="cortex_script_quota", limit=5,
                )
            with self.assertRaises(HTTPException) as ctx:
                await enforce_daily_quota(
                    adapter, request=request, action="cortex_script_quota", limit=5,
                )
            return ctx.exception

        exc = asyncio.run(run())
        self.assertEqual(exc.status_code, 429)
        self.assertEqual(exc.headers["Retry-After"], "86400")

    def test_different_ips_get_independent_quotas(self) -> None:
        adapter = FakeRedisAdapter()

        async def run():
            for _ in range(5):
                await enforce_daily_quota(
                    adapter,
                    request=_Request(),
                    action="cortex_script_quota",
                    limit=5,
                )
            # a different IP should not have been affected by the above.
            other = _Request()
            other.client = type("Client", (), {"host": "198.51.100.9"})()
            await enforce_daily_quota(
                adapter, request=other, action="cortex_script_quota", limit=5,
            )

        asyncio.run(run())  # should not raise


class CortexProxyEndpointTests(unittest.TestCase):
    def test_proxy_forwards_to_cortex_app(self) -> None:
        forwarded = Response(status_code=200)
        request = _Request(
            headers={CORTEX_PROOF_HEADER: compute_app_proof()},
            body=b'{"model":"gpt-4","messages":[]}',
        )
        with patch.object(
            cortex_route.proxy_service, "forward_request", new=AsyncMock(return_value=forwarded)
        ) as forward:
            result = asyncio.run(
                cortex_proxy_endpoint("chat/completions", request, Response())
            )

        self.assertIs(result, forwarded)
        self.assertEqual(forward.await_args.args[0], "cortex")
        self.assertEqual(forward.await_args.args[1], "/chat/completions")

    def test_forced_tier0_fields_reach_the_upstream_body(self) -> None:
        forwarded = Response(status_code=200)
        request = _Request(
            headers={CORTEX_PROOF_HEADER: compute_app_proof()},
            body=b'{"model":"gpt-4-turbo","messages":[]}',
        )
        with patch.object(
            cortex_route.proxy_service, "forward_request", new=AsyncMock(return_value=forwarded)
        ) as forward:
            asyncio.run(cortex_proxy_endpoint("chat/completions", request, Response()))

        sent_body = forward.await_args.kwargs["body_override"]
        self.assertIn(TIER0_MODEL.encode(), sent_body)
        self.assertNotIn(b"gpt-4-turbo", sent_body)

    def test_valid_proof_bypasses_the_daily_quota(self) -> None:
        forwarded = Response(status_code=200)
        request = _Request(headers={CORTEX_PROOF_HEADER: compute_app_proof()})
        with (
            patch.object(cortex_route, "enforce_daily_quota", new=AsyncMock()) as quota,
            patch.object(
                cortex_route.proxy_service, "forward_request", new=AsyncMock(return_value=forwarded)
            ),
        ):
            asyncio.run(cortex_proxy_endpoint("execute", request, Response()))

        quota.assert_not_called()

    def test_missing_proof_triggers_the_daily_quota_check(self) -> None:
        forwarded = Response(status_code=200)
        request = _Request(headers={})
        with (
            patch.object(cortex_route, "get_redis_adapter", return_value=object()),
            patch.object(cortex_route, "enforce_daily_quota", new=AsyncMock()) as quota,
            patch.object(
                cortex_route.proxy_service, "forward_request", new=AsyncMock(return_value=forwarded)
            ),
        ):
            asyncio.run(cortex_proxy_endpoint("execute", request, Response()))

        quota.assert_awaited_once()
        self.assertEqual(quota.await_args.kwargs["limit"], app_settings().CORTEX_DAILY_TEST_LIMIT)

    def test_sixth_unattested_request_returns_429_response(self) -> None:
        request = _Request(headers={})
        with (
            patch.object(cortex_route, "get_redis_adapter", return_value=object()),
            patch.object(
                cortex_route,
                "enforce_daily_quota",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=429, detail="Daily test limit reached")
                ),
            ),
        ):
            result = asyncio.run(cortex_proxy_endpoint("execute", request, Response()))

        self.assertEqual(result.status_code, 429)


if __name__ == "__main__":
    unittest.main()
