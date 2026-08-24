import asyncio
import json
import os
import time
import unittest


os.environ.setdefault("API_KEY_SECRET", "test-admin-key")
os.environ.setdefault("DEFAULT_DB_HOST", "localhost")
os.environ.setdefault("DEFAULT_DB_PORT", "5432")
os.environ.setdefault("DEFAULT_DB_USER", "test")
os.environ.setdefault("DEFAULT_DB_PASSWORD", "test")
os.environ.setdefault("DEFAULT_DB_NAME", "test")
os.environ.setdefault("FERNET_KEY_SECRET", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("SERVER_FERNET_KEY_SECRET", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")

from src.domain.services.exchange_auth_app_service import ExchangeAuthService
from src.domain.services.local_proxy_service import LocalProxyService
from src.presentation.handler.exchange_auth_app_handler import (
    exchange_auth_sync,
    register_auth_exchange_artifact,
)


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def k(self, *parts):
        return ":".join(map(str, parts))

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def getdel(self, key):
        return self.values.pop(key, None)


class SessionExchangeTests(unittest.TestCase):
    def _token(self):
        service = ExchangeAuthService()
        payload = {
            "jti": "one-use-id",
            "app": "certifications",
            "provider": "supabase",
            "id": 7,
            "uuid_id": "user-uuid",
            "email": "user@example.com",
            "access_level": 3,
            "is_active": True,
            "provider_user_id": "supabase-subject",
            "exp": int(time.time()) + 30,
        }
        return service.cryptography_service.encrypt(json.dumps(payload).encode()).decode()

    def test_artifact_can_be_redeemed_once(self):
        async def run():
            adapter = MemoryRedis()
            token = self._token()
            await register_auth_exchange_artifact(adapter, token)
            cookie = await exchange_auth_sync(adapter, token, expected_app="certifications")
            self.assertEqual(cookie.provider_user_id, "supabase-subject")
            with self.assertRaises(Exception):
                await exchange_auth_sync(adapter, token, expected_app="certifications")

        asyncio.run(run())

    def test_proxy_removes_client_identity_header(self):
        headers = LocalProxyService().adjust_request_headers(
            {"X-UUID": "forged", "Host": "example", "Accept": "application/json"}
        )
        self.assertNotIn("X-UUID", headers)
        self.assertNotIn("Host", headers)
        self.assertEqual(headers["Accept"], "application/json")
