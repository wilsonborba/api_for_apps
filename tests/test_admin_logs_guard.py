import asyncio
import os
import unittest
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

from fastapi import HTTPException, Response
from src.core.settings import app_settings
from src.presentation.handler.auth import verify_admin_auth
from src.presentation.routes import apps_route, cortex_route


class _Request:
    def __init__(self, headers=None, cookies=None, method="GET", path="/"):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.method = method
        self.url = type("URL", (), {"path": path, "scheme": "https", "hostname": "localhost", "query": ""})()
        self.client = type("Client", (), {"host": "127.0.0.1"})()


class AdminLogsGuardTests(unittest.TestCase):
    def test_verify_admin_auth_allows_valid_admin_api_key(self):
        req = _Request(headers={"authorization": "test-admin-key"})
        res = Response()
        result = asyncio.run(verify_admin_auth(req, res, api_key_secret="test-admin-key"))
        self.assertTrue(result)

    def test_verify_admin_auth_allows_access_level_1_user(self):
        req = _Request(cookies={"sid": "admin-session-id"})
        res = Response()
        with (
            patch("src.presentation.handler.auth.verify_auth", new=AsyncMock(return_value=True)),
            patch("src.presentation.handler.auth.get_redis_adapter", return_value=object()),
            patch(
                "src.presentation.handler.auth.get_user_info_from_redis_sync",
                new=AsyncMock(return_value={"user_uuid_id": "admin-uuid", "access_level": 1, "email": "admin@asodya.com"}),
            ),
        ):
            result = asyncio.run(verify_admin_auth(req, res))
            self.assertTrue(result)

    def test_verify_admin_auth_rejects_regular_user_access_level_3(self):
        req = _Request(cookies={"sid": "user-session-id"})
        res = Response()
        with (
            patch("src.presentation.handler.auth.verify_auth", new=AsyncMock(return_value=True)),
            patch("src.presentation.handler.auth.get_redis_adapter", return_value=object()),
            patch(
                "src.presentation.handler.auth.get_user_info_from_redis_sync",
                new=AsyncMock(return_value={"user_uuid_id": "user-uuid", "access_level": 3, "email": "user@asodya.com"}),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(verify_admin_auth(req, res))
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertIn("Admin access required", ctx.exception.detail)

    def test_apps_proxy_blocks_log_stream_for_regular_user(self):
        req = _Request(cookies={"sid": "user-session-id"})
        res = Response()
        with (
            patch("src.presentation.routes.apps_route.verify_admin_auth", side_effect=HTTPException(status_code=403, detail="Forbidden: Admin access required.")),
        ):
            result = asyncio.run(apps_route.proxy_endpoint("certifications", "logs/stream", req, res))
            self.assertEqual(result.status_code, 403)

    def test_apps_proxy_allows_log_stream_for_admin(self):
        proxied_response = Response(status_code=200)
        req = _Request(cookies={"sid": "admin-session-id"})
        res = Response()
        with (
            patch("src.presentation.routes.apps_route.verify_admin_auth", new=AsyncMock(return_value=True)),
            patch.object(
                apps_route.proxy_service,
                "forward_request",
                new=AsyncMock(return_value=proxied_response),
            ) as forward_mock,
        ):
            result = asyncio.run(apps_route.proxy_endpoint("certifications", "logs/stream", req, res))
            self.assertIs(result, proxied_response)
            forward_mock.assert_awaited_once()

    def test_cortex_proxy_blocks_logs_for_non_admin(self):
        req = _Request()
        res = Response()
        with (
            patch("src.presentation.routes.cortex_route.verify_admin_auth", side_effect=HTTPException(status_code=403, detail="Forbidden: Admin access required.")),
        ):
            result = asyncio.run(cortex_route.cortex_proxy_endpoint("logs/stream", req, res))
            self.assertEqual(result.status_code, 403)
