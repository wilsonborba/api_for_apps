from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Response

from src.domain.services.legal_acceptance_service import (
    InvalidLegalDocumentTypeError,
    LegalAcceptanceService,
)
from src.presentation.routes import legal_route
from src.presentation.routes.legal_route import (
    AcceptLegalDocumentRequestModel,
    get_legal_status,
    post_accept_legal_document,
)


class _Request:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class _FakeDBAdapter:
    """In-memory stand-in for DBAdapter, just enough surface for
    LegalAcceptanceService (read_all/insert_row/update_row)."""

    def __init__(self):
        self._rows = []

    def read_all(self, table_name, schema=None):
        return [dict(row) for row in self._rows]

    def insert_row(self, table_name, data, schema=None):
        self._rows.append(dict(data))
        return (data["id"],)

    def update_row(self, table_name, id_value, data, id_column="id", schema=None):
        for row in self._rows:
            if row.get(id_column) == id_value:
                row.update(data)
                return 1
        return 0


class RequireUserUuidIdTests(unittest.TestCase):
    """Legal acceptance is never anonymous: a valid admin key alone (which
    is all verify_auth by itself requires) must not be enough."""

    def test_missing_session_cookie_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(legal_route._require_user_uuid_id(_Request(cookies={})))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_session_with_no_redis_entry_is_rejected(self):
        with (
            patch.object(legal_route, "get_redis_adapter", return_value=object()),
            patch.object(legal_route, "get_user_info_from_redis_sync", new=AsyncMock(return_value=None)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(legal_route._require_user_uuid_id(_Request(cookies={"sid": "abc"})))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_session_missing_user_uuid_id_is_rejected(self):
        with (
            patch.object(legal_route, "get_redis_adapter", return_value=object()),
            patch.object(
                legal_route, "get_user_info_from_redis_sync", new=AsyncMock(return_value={"email": "a@b.c"})
            ),
        ):
            with self.assertRaises(HTTPException):
                asyncio.run(legal_route._require_user_uuid_id(_Request(cookies={"sid": "abc"})))

    def test_valid_session_returns_the_user_uuid_id(self):
        with (
            patch.object(legal_route, "get_redis_adapter", return_value=object()),
            patch.object(
                legal_route,
                "get_user_info_from_redis_sync",
                new=AsyncMock(return_value={"user_uuid_id": "user-uuid-123"}),
            ),
        ):
            user_uuid_id = asyncio.run(legal_route._require_user_uuid_id(_Request(cookies={"sid": "abc"})))
        self.assertEqual(user_uuid_id, "user-uuid-123")


class LegalRouteHandlerTests(unittest.TestCase):
    def _patched_identity(self, user_uuid_id="user-uuid-123"):
        return patch.object(legal_route, "_require_user_uuid_id", new=AsyncMock(return_value=user_uuid_id))

    def test_get_legal_status_returns_the_service_result(self):
        fake_status = {"terms_of_service": {"accepted": False}}
        with (
            self._patched_identity(),
            patch.object(legal_route.legal_acceptance_service, "get_status", return_value=fake_status) as get_status,
        ):
            result = asyncio.run(get_legal_status(_Request(cookies={"sid": "abc"}), Response()))

        get_status.assert_called_once_with("user-uuid-123")
        self.assertEqual(result.status_code, 200)

    def test_accept_rejects_an_unknown_document_type(self):
        with (
            self._patched_identity(),
            patch.object(
                legal_route.legal_acceptance_service,
                "accept",
                side_effect=InvalidLegalDocumentTypeError("Unknown document_type."),
            ),
        ):
            result = asyncio.run(
                post_accept_legal_document(
                    AcceptLegalDocumentRequestModel(document_type="not_a_real_document"),
                    _Request(cookies={"sid": "abc"}),
                    Response(),
                )
            )
        self.assertEqual(result.status_code, 400)

    def test_accept_returns_the_service_result(self):
        entry = {
            "accepted": True,
            "version": "2026-09-14",
            "accepted_at": "2026-09-14T10:00:00Z",
            "current_version": "2026-09-14",
        }
        with (
            self._patched_identity(),
            patch.object(legal_route.legal_acceptance_service, "accept", return_value=entry) as accept,
        ):
            result = asyncio.run(
                post_accept_legal_document(
                    AcceptLegalDocumentRequestModel(document_type="terms_of_service"),
                    _Request(cookies={"sid": "abc"}),
                    Response(),
                )
            )

        accept.assert_called_once_with("user-uuid-123", "terms_of_service")
        self.assertEqual(result.status_code, 200)


class LegalAcceptanceServiceTests(unittest.TestCase):
    """Exercises the actual upsert/version-comparison logic against an
    in-memory DBAdapter stand-in, no real Postgres required."""

    def _service(self, versions):
        service = LegalAcceptanceService(db_adapter=_FakeDBAdapter())
        service.settings = type("S", (), {"LEGAL_DOCUMENT_VERSIONS": versions})()
        return service

    def test_status_reports_not_accepted_when_no_row_exists(self):
        service = self._service({"terms_of_service": "2026-09-14"})
        status = service.get_status("user-1")
        self.assertEqual(
            status["terms_of_service"],
            {
                "accepted": False,
                "version": None,
                "accepted_at": None,
                "current_version": "2026-09-14",
            },
        )

    def test_accept_then_status_shows_accepted(self):
        service = self._service({"terms_of_service": "2026-09-14"})
        entry = service.accept("user-1", "terms_of_service")
        self.assertTrue(entry["accepted"])
        self.assertEqual(entry["version"], "2026-09-14")

        status = service.get_status("user-1")
        self.assertTrue(status["terms_of_service"]["accepted"])
        self.assertEqual(status["terms_of_service"]["version"], "2026-09-14")

    def test_bumping_the_configured_version_forces_re_acceptance(self):
        service = self._service({"terms_of_service": "2026-09-14"})
        service.accept("user-1", "terms_of_service")

        # Simulate a content change: the configured current version moves on.
        service.settings = type("S", (), {"LEGAL_DOCUMENT_VERSIONS": {"terms_of_service": "2026-10-01"}})()

        status = service.get_status("user-1")
        entry = status["terms_of_service"]
        self.assertFalse(entry["accepted"])
        # The audit row itself is preserved, not deleted.
        self.assertEqual(entry["version"], "2026-09-14")
        self.assertEqual(entry["current_version"], "2026-10-01")

        # Re-accepting records the new current version.
        entry = service.accept("user-1", "terms_of_service")
        self.assertTrue(entry["accepted"])
        self.assertEqual(entry["version"], "2026-10-01")

    def test_accept_rejects_an_unknown_document_type(self):
        service = self._service({"terms_of_service": "2026-09-14"})
        with self.assertRaises(InvalidLegalDocumentTypeError):
            service.accept("user-1", "not_a_real_document")


if __name__ == "__main__":
    unittest.main()
