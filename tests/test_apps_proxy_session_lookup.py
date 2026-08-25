import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Response

from src.presentation.routes import apps_route


class _Request:
    method = "GET"
    cookies = {"sid": "session-id"}


class AppsProxySessionLookupTests(unittest.TestCase):
    def test_protected_proxy_uses_redis_session_identity(self):
        proxied_response = Response(status_code=200)
        with (
            patch.object(apps_route, "verify_auth", new=AsyncMock()),
            patch.object(apps_route, "get_redis_adapter", return_value=object()),
            patch.object(
                apps_route,
                "get_user_info_from_redis_sync",
                new=AsyncMock(return_value={"user_uuid_id": "user-uuid"}),
            ),
            patch.object(
                apps_route.proxy_service,
                "forward_request",
                new=AsyncMock(return_value=proxied_response),
            ) as forward_request,
        ):
            result = asyncio.run(
                apps_route.proxy_endpoint(
                    "certifications",
                    "tokens/user_tokens",
                    _Request(),
                    Response(),
                ),
            )

        self.assertIs(result, proxied_response)
        self.assertEqual(forward_request.await_args.kwargs["internal_headers"], {"x-uuid": "user-uuid"})
