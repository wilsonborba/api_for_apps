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
from src.presentation.routes import apps_route


class _Request:
    def __init__(self, headers=None, cookies=None, method="GET", path="/"):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.method = method
        self.url = type("URL", (), {"path": path, "scheme": "https", "hostname": "localhost", "query": ""})()
        self.client = type("Client", (), {"host": "127.0.0.1"})()


class DomainRouteMatchingTests(unittest.TestCase):
    def test_landing_and_projects_are_public(self):
        self.assertTrue(apps_route._is_public_proxy_request("domain", "landing", "GET"))
        self.assertTrue(apps_route._is_public_proxy_request("domain", "projects", "GET"))
        self.assertTrue(apps_route._is_public_proxy_request("domain", "projects/wojo-club", "GET"))
        self.assertTrue(apps_route._is_public_proxy_request("domain", "search", "GET"))

    def test_protected_files_route_forces_auth_despite_public_prefix_match(self):
        # matches the broad "/projects/*" public glob...
        self.assertTrue(apps_route._is_public_proxy_request("domain", "projects/wojo-club/files", "GET"))
        # ...but force-auth overrides it, so it never proxies without a session.
        self.assertTrue(apps_route._is_force_auth_request("domain", "projects/wojo-club/files", "GET"))

    def test_mutating_project_routes_are_admin_protected(self):
        self.assertTrue(apps_route._is_admin_protected_request("domain", "projects", "POST"))
        self.assertTrue(apps_route._is_admin_protected_request("domain", "projects/wojo-club", "PUT"))
        self.assertTrue(apps_route._is_admin_protected_request("domain", "projects/wojo-club", "PATCH"))
        self.assertTrue(apps_route._is_admin_protected_request("domain", "projects/wojo-club", "DELETE"))
        self.assertTrue(apps_route._is_admin_protected_request("domain", "projects/wojo-club/files", "POST"))
        self.assertTrue(apps_route._is_admin_protected_request("domain", "categories", "POST"))
        self.assertTrue(apps_route._is_admin_protected_request("domain", "flutter-icons", "POST"))
        # a GET on the same path only needs a regular session, not admin.
        self.assertFalse(apps_route._is_admin_protected_request("domain", "projects/wojo-club/files", "GET"))


class ProxyEndpointApiKeyTests(unittest.TestCase):
    """Regression coverage for the bug fixed alongside issue #28: calling
    verify_admin_auth/verify_auth directly (not as a FastAPI Depends())
    left api_key_secret bound to an unresolved Security() default, so
    X-API-KEY was silently ignored by the generic app proxy."""

    def test_admin_protected_route_accepts_x_api_key_header(self):
        proxied_response = Response(status_code=201)
        # Real Starlette headers are case-insensitive; "Authorization" here
        # matches settings.API_ADMIN_KEY_NAME exactly, same as a real header.
        request = _Request(headers={"Authorization": "test-admin-key"}, method="POST")
        with (
            patch.object(apps_route, "get_redis_adapter", return_value=object()),
            patch.object(apps_route.proxy_service, "forward_request", new=AsyncMock(return_value=proxied_response)) as forward_request,
        ):
            result = asyncio.run(apps_route.proxy_endpoint("domain", "projects", request, Response()))

        self.assertIs(result, proxied_response)
        forward_request.assert_awaited_once()

    def test_admin_protected_route_rejects_missing_credentials(self):
        request = _Request(headers={}, cookies={}, method="POST")
        with patch("src.presentation.handler.auth.get_redis_adapter", return_value=object()):
            result = asyncio.run(apps_route.proxy_endpoint("domain", "projects", request, Response()))
        self.assertEqual(result.status_code, 403)
