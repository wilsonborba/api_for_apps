from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Response

from src.presentation.routes import apps_route
from src.presentation.routes import waitlist_route
from src.presentation.routes.waitlist_route import WaitlistRequest, join_waitlist


class _Request:
    method = "POST"
    client = type("Client", (), {"host": "127.0.0.1"})()
    headers = {"content-type": "application/json"}

    async def body(self) -> bytes:
        return b'{"email":"person@example.com","plan":"free"}'


class PublicWaitlistContractTests(unittest.TestCase):
    def test_policy_allows_only_named_public_waitlist_post(self) -> None:
        self.assertTrue(apps_route._is_public_proxy_request("certifications", "waitlist", "POST"))
        self.assertFalse(apps_route._is_public_proxy_request("certifications", "studies", "POST"))
        self.assertFalse(apps_route._is_public_proxy_request("other", "waitlist", "POST"))

    def test_waitlist_forwards_server_derived_context(self) -> None:
        forwarded = Response(status_code=202)
        with (
            patch.object(waitlist_route, "_rate_limit", new=AsyncMock()),
            patch.object(waitlist_route._supabase, "user_exists_by_email", return_value=True),
            patch.object(waitlist_route._proxy, "forward_request", new=AsyncMock(return_value=forwarded)) as forward,
        ):
            result = asyncio.run(
                join_waitlist(
                    WaitlistRequest(email=" Person@Example.com ", plan="free"),
                    _Request(),
                    Response(),
                )
            )

        self.assertIs(result, forwarded)
        internal = forward.await_args.kwargs["internal_headers"]
        self.assertEqual(internal["x-certifications-waitlist-registered"], "true")
        self.assertTrue(internal["x-certifications-service-key"])
