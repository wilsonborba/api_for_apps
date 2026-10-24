import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Response

from src.presentation.routes import apps_route


class _Request:
    method = "GET"
    cookies = {"sid": "session-id"}
    headers = {}


class AppsProxySessionLookupTests(unittest.TestCase):
    def test_reports_routes_to_headless_engine(self):
        self.assertEqual(apps_route.proxy_service.get_port("reports"), 8109)

    def test_reports_landing_reads_are_public(self):
        for path in ("projects", "projects/demo", "site", "stats"):
            self.assertTrue(apps_route._is_public_proxy_request("reports", path, "GET"), path)

    def test_reports_data_reads_remain_session_protected(self):
        self.assertTrue(
            apps_route._is_force_auth_request("reports", "projects/demo/reports/summary", "GET")
        )
        self.assertTrue(
            apps_route._is_force_auth_request("reports", "projects/demo/datasets/1", "GET")
        )

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
