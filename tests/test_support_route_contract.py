from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Response

from src.dal.remote.fsm_media_adapter import FsmConfigurationError, FsmStorageError
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
    post_upload_attachment,
)
from src.domain.services.support_ticket_service import SupportTicketNotFoundError


class _Request:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class _UploadFile:
    """Stand-in for fastapi.UploadFile; only what the route reads."""

    def __init__(self, content: bytes, filename: str = "photo.png", content_type: str = "image/png"):
        self._content = content
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._content


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

    def test_valid_session_returns_the_user_uuid_id_and_access_level(self):
        with (
            patch.object(support_route, "get_redis_adapter", return_value=object()),
            patch.object(
                support_route,
                "get_user_info_from_redis_sync",
                new=AsyncMock(return_value={"user_uuid_id": "user-uuid-123", "access_level": 1}),
            ),
        ):
            identity = asyncio.run(support_route._require_identity(_Request(cookies={"sid": "abc"})))
        self.assertEqual(identity, ("user-uuid-123", 1))

    def test_missing_access_level_defaults_to_the_regular_user_level(self):
        with (
            patch.object(support_route, "get_redis_adapter", return_value=object()),
            patch.object(
                support_route,
                "get_user_info_from_redis_sync",
                new=AsyncMock(return_value={"user_uuid_id": "user-uuid-123"}),
            ),
        ):
            identity = asyncio.run(support_route._require_identity(_Request(cookies={"sid": "abc"})))
        self.assertEqual(identity, ("user-uuid-123", 3))


class IsAdminTests(unittest.TestCase):
    def test_access_level_one_is_admin(self):
        self.assertTrue(support_route._is_admin(1))

    def test_access_level_two_and_three_are_not_admin(self):
        self.assertFalse(support_route._is_admin(2))
        self.assertFalse(support_route._is_admin(3))


class SupportRouteHandlerTests(unittest.TestCase):
    def _patched_identity(self, user_uuid_id="user-uuid-123", access_level=3):
        return patch.object(
            support_route, "_require_identity", new=AsyncMock(return_value=(user_uuid_id, access_level))
        )

    def test_upload_attachment_returns_the_fsm_reference(self):
        fake_adapter = MagicMock()
        fake_adapter.upload = AsyncMock(return_value="support/user-uuid-123/abc123.png")
        with (
            self._patched_identity(),
            patch.object(support_route, "_fsm_adapter", return_value=fake_adapter),
        ):
            result = asyncio.run(
                post_upload_attachment(
                    _Request(cookies={"sid": "abc"}),
                    Response(),
                    file=_UploadFile(b"binary-data"),
                )
            )

        fake_adapter.upload.assert_called_once_with(
            album="support-user-uuid-123",
            filename="photo.png",
            body=b"binary-data",
            content_type="image/png",
        )
        self.assertEqual(result.status_code, 201)

    def test_upload_attachment_rejects_a_file_over_the_size_cap(self):
        oversized = b"x" * (support_route.SUPPORT_ATTACHMENT_MAX_BYTES + 1)
        with self._patched_identity():
            result = asyncio.run(
                post_upload_attachment(
                    _Request(cookies={"sid": "abc"}),
                    Response(),
                    file=_UploadFile(oversized),
                )
            )
        self.assertEqual(result.status_code, 400)

    def test_upload_attachment_maps_missing_fsm_configuration_to_503(self):
        fake_adapter = MagicMock()
        fake_adapter.upload = AsyncMock(side_effect=FsmConfigurationError("not configured"))
        with (
            self._patched_identity(),
            patch.object(support_route, "_fsm_adapter", return_value=fake_adapter),
        ):
            result = asyncio.run(
                post_upload_attachment(
                    _Request(cookies={"sid": "abc"}), Response(), file=_UploadFile(b"data")
                )
            )
        self.assertEqual(result.status_code, 503)

    def test_upload_attachment_maps_fsm_storage_failure_to_502(self):
        fake_adapter = MagicMock()
        fake_adapter.upload = AsyncMock(side_effect=FsmStorageError("rejected"))
        with (
            self._patched_identity(),
            patch.object(support_route, "_fsm_adapter", return_value=fake_adapter),
        ):
            result = asyncio.run(
                post_upload_attachment(
                    _Request(cookies={"sid": "abc"}), Response(), file=_UploadFile(b"data")
                )
            )
        self.assertEqual(result.status_code, 502)

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

        list_mock.assert_called_once_with(
            user_id="user-uuid-123", source_app=None, status=None, is_admin=False
        )

    def test_list_tickets_passes_is_admin_true_for_an_access_level_one_caller(self):
        with (
            self._patched_identity(access_level=1),
            patch.object(support_route.support_ticket_service, "list_tickets", return_value=[]) as list_mock,
        ):
            asyncio.run(
                get_list_tickets(
                    _Request(cookies={"sid": "abc"}), Response(), source_app=None, status_filter=None
                )
            )

        list_mock.assert_called_once_with(
            user_id="user-uuid-123", source_app=None, status=None, is_admin=True
        )

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
            ticket_id="ticket-1",
            user_id="user-uuid-123",
            body="hi",
            attachment_reference="fsm://bucket/key.png",
            is_admin=False,
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
