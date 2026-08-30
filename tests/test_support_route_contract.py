from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Response

from src.presentation.routes import support_route
from src.presentation.routes.support_route import (
    CreateSupportTicketRequestModel,
    PostSupportMessageRequestModel,
    get_list_tickets,
    get_ticket,
    patch_mark_message_read,
    patch_mark_ticket_read,
    post_create_ticket,
    post_message,
)
from src.domain.services.support_ticket_service import SupportTicketNotFoundError


class _Request:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class RequireIdentityTests(unittest.TestCase):
    """Support tickets are never anonymous: a valid admin key alone (which
    is all verify_auth by itself would require) must not be enough."""

    def test_missing_session_cookie_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(support_route._require_identity(_Request(cookies={})))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_session_with_no_redis_entry_is_rejected(self):
        with (
            patch.object(support_route, "get_redis_adapter", return_value=object()),
            patch.object(support_route, "get_user_info_from_redis_sync", new=AsyncMock(return_value=None)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(support_route._require_identity(_Request(cookies={"sid": "abc"})))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_session_missing_user_uuid_id_is_rejected(self):
        with (
            patch.object(support_route, "get_redis_adapter", return_value=object()),
            patch.object(
                support_route, "get_user_info_from_redis_sync", new=AsyncMock(return_value={"email": "a@b.c"})
            ),
        ):
            with self.assertRaises(HTTPException):
                asyncio.run(support_route._require_identity(_Request(cookies={"sid": "abc"})))

    def test_valid_session_returns_the_user_uuid_id(self):
        with (
            patch.object(support_route, "get_redis_adapter", return_value=object()),
            patch.object(
                support_route,
                "get_user_info_from_redis_sync",
                new=AsyncMock(return_value={"user_uuid_id": "user-uuid-123"}),
            ),
        ):
            identity = asyncio.run(support_route._require_identity(_Request(cookies={"sid": "abc"})))
        self.assertEqual(identity, "user-uuid-123")


class SupportRouteHandlerTests(unittest.TestCase):
    def _patched_identity(self, user_uuid_id="user-uuid-123"):
        return patch.object(support_route, "_require_identity", new=AsyncMock(return_value=user_uuid_id))

    def test_create_ticket_uses_the_caller_identity_and_normalizes_source_app(self):
        created = {"id": "ticket-1", "status": "open"}
        with (
            self._patched_identity(),
            patch.object(support_route.support_ticket_service, "create_ticket", return_value=created) as create,
        ):
            result = asyncio.run(
                post_create_ticket(
                    CreateSupportTicketRequestModel(
                        source_app=" Certifications ", subject=" Help ", body=" Something broke "
                    ),
                    _Request(cookies={"sid": "abc"}),
                    Response(),
                )
            )

        create.assert_called_once_with(
            user_id="user-uuid-123",
            source_app="certifications",
            subject="Help",
            body="Something broke",
            attachment_reference=None,
        )
        self.assertEqual(result.status_code, 201)

    def test_list_tickets_is_scoped_to_the_caller_identity(self):
        # source_app/status_filter are declared with fastapi.Query(...)
        # defaults, only resolved to real values by FastAPI's own request
        # handling; called directly here, they must be passed explicitly.
        with (
            self._patched_identity(),
            patch.object(support_route.support_ticket_service, "list_tickets", return_value=[]) as list_mock,
        ):
            asyncio.run(
                get_list_tickets(
                    _Request(cookies={"sid": "abc"}), Response(), source_app=None, status_filter=None
                )
            )

        list_mock.assert_called_once_with(user_id="user-uuid-123", source_app=None, status=None)

    def test_list_tickets_rejects_an_unknown_status_filter(self):
        with self._patched_identity():
            result = asyncio.run(
                get_list_tickets(_Request(cookies={"sid": "abc"}), Response(), status_filter="not-a-real-status")
            )
        self.assertEqual(result.status_code, 400)

    def test_get_ticket_maps_not_found_to_404(self):
        with (
            self._patched_identity(),
            patch.object(
                support_route.support_ticket_service,
                "get_ticket",
                side_effect=SupportTicketNotFoundError(),
            ),
        ):
            result = asyncio.run(get_ticket("missing-id", _Request(cookies={"sid": "abc"}), Response()))
        self.assertEqual(result.status_code, 404)

    def test_post_message_forwards_the_attachment_reference(self):
        with (
            self._patched_identity(),
            patch.object(
                support_route.support_ticket_service, "post_message", return_value={"id": "msg-1"}
            ) as post_mock,
        ):
            result = asyncio.run(
                post_message(
                    "ticket-1",
                    PostSupportMessageRequestModel(body="hi", attachment_reference="fsm://bucket/key.png"),
                    _Request(cookies={"sid": "abc"}),
                    Response(),
                )
            )

        post_mock.assert_called_once_with(
            ticket_id="ticket-1", user_id="user-uuid-123", body="hi", attachment_reference="fsm://bucket/key.png"
        )
        self.assertEqual(result.status_code, 201)

    def test_mark_ticket_read_maps_not_found_to_404(self):
        with (
            self._patched_identity(),
            patch.object(
                support_route.support_ticket_service,
                "mark_ticket_read",
                side_effect=SupportTicketNotFoundError(),
            ),
        ):
            result = asyncio.run(patch_mark_ticket_read("ticket-1", _Request(cookies={"sid": "abc"}), Response()))
        self.assertEqual(result.status_code, 404)

    def test_mark_message_read_returns_404_when_message_is_not_found(self):
        with (
            self._patched_identity(),
            patch.object(support_route.support_ticket_service, "mark_message_read", return_value=False),
        ):
            result = asyncio.run(
                patch_mark_message_read(
                    "ticket-1", "message-1", _Request(cookies={"sid": "abc"}), Response()
                )
            )
        self.assertEqual(result.status_code, 404)

    def test_mark_message_read_succeeds(self):
        with (
            self._patched_identity(),
            patch.object(support_route.support_ticket_service, "mark_message_read", return_value=True),
        ):
            result = asyncio.run(
                patch_mark_message_read(
                    "ticket-1", "message-1", _Request(cookies={"sid": "abc"}), Response()
                )
            )
        self.assertEqual(result.status_code, 200)


if __name__ == "__main__":
    unittest.main()
