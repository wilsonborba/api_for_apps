import asyncio
import os
import unittest
from types import SimpleNamespace
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

from src.presentation.routes import user_route


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def k(self, *parts):
        return ":".join(map(str, parts))

    async def set(self, key, value, ex=None, nx=False):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


class OAuthAppContractTests(unittest.TestCase):
    def test_start_normalizes_and_persists_initiating_app(self):
        async def run():
            adapter = MemoryRedis()
            with (
                patch.object(user_route, "get_redis_adapter", return_value=adapter),
                patch.object(user_route.secrets, "token_urlsafe", return_value="state"),
                patch.object(user_route.supabase_auth_adapter, "generate_pkce_verifier", return_value="verifier"),
                patch.object(user_route.supabase_auth_adapter, "generate_pkce_challenge", return_value="challenge"),
                patch.object(user_route.supabase_auth_adapter, "get_oauth_authorization_url", return_value="https://provider.example/auth"),
            ):
                result = await user_route.post_oauth_start(
                    SimpleNamespace(),
                    user_route.OAuthStartRequestModel(provider="google", app="CERTIFICATIONS"),
                )

            self.assertEqual(result.status_code, 200)
            self.assertEqual(adapter.values[adapter.k(user_route.settings.OAUTH_STATE_PREFIX, "state")]["app"], "certifications")

        asyncio.run(run())

    def test_callback_uses_app_stored_in_oauth_state(self):
        async def run():
            adapter = MemoryRedis()
            adapter.values[adapter.k(user_route.settings.OAUTH_STATE_PREFIX, "state")] = {
                "app": "certifications",
                "code_verifier": "verifier",
            }
            with (
                patch.object(user_route, "get_redis_adapter", return_value=adapter),
                patch.object(user_route.supabase_auth_adapter, "exchange_code_for_session", return_value={"session": {"access_token": "token"}}),
                patch.object(user_route, "log_in_user_from_auth_session", return_value="artifact") as login,
                patch.object(user_route, "register_auth_exchange_artifact", new=AsyncMock()),
            ):
                result = await user_route.post_oauth_callback(
                    SimpleNamespace(),
                    user_route.OAuthCallbackRequestModel(code="code", state="state"),
                )

            self.assertEqual(result.status_code, 200)
            login.assert_called_once_with("token", "certifications")

        asyncio.run(run())

    def test_callback_rejects_legacy_state_without_an_app(self):
        async def run():
            adapter = MemoryRedis()
            key = adapter.k(user_route.settings.OAUTH_STATE_PREFIX, "state")
            adapter.values[key] = {"code_verifier": "verifier"}
            with patch.object(user_route, "get_redis_adapter", return_value=adapter):
                result = await user_route.post_oauth_callback(
                    SimpleNamespace(),
                    user_route.OAuthCallbackRequestModel(code="code", state="state"),
                )

            self.assertEqual(result.status_code, 400)
            self.assertNotIn(key, adapter.values)

        asyncio.run(run())
