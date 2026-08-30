from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from src.dal.local.db_adapter import DBAdapter
from src.dal.remote.support_document_store import InMemorySupportTicketDocumentStore
from src.domain.services.support_ticket_service import (
    SupportTicketNotFoundError,
    SupportTicketService,
)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "dal"
    / "migrations"
    / "versions"
    / "20260830_01_support_tickets.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "support_tickets_migration_under_test", _MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupportTicketServiceTests(unittest.TestCase):
    """Exercises the actual 20260830_01 migration DDL and the service
    against a throwaway in-memory SQLite database (never the live Postgres
    appdb), with an in-memory document store standing in for CouchDB."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        migration = _load_migration_module()
        with self.engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                migration.upgrade()
            conn.commit()

        self.service = SupportTicketService(
            db_adapter=DBAdapter(engine=self.engine),
            document_store=InMemorySupportTicketDocumentStore(),
        )

    def test_create_ticket_opens_index_row_and_first_message(self):
        ticket = self.service.create_ticket(
            user_id="user-1", source_app="certifications", subject="Help", body="Body text"
        )
        self.assertEqual(ticket["status"], "open")
        self.assertEqual(ticket["source_app"], "certifications")
        self.assertEqual(len(ticket["messages"]), 1)
        self.assertFalse(ticket["messages"][0]["read"])
        self.assertIsNone(ticket["messages"][0]["attachment_reference"])

    def test_create_ticket_carries_an_attachment_reference(self):
        ticket = self.service.create_ticket(
            user_id="user-1",
            source_app="certifications",
            subject=None,
            body="See attached",
            attachment_reference="fsm://bucket/key.png",
        )
        self.assertEqual(ticket["messages"][0]["attachment_reference"], "fsm://bucket/key.png")

    def test_list_tickets_is_scoped_to_the_caller(self):
        self.service.create_ticket(user_id="user-1", source_app="certifications", subject=None, body="a")
        self.service.create_ticket(user_id="user-2", source_app="certifications", subject=None, body="b")

        self.assertEqual(len(self.service.list_tickets(user_id="user-1")), 1)
        self.assertEqual(len(self.service.list_tickets(user_id="user-2")), 1)
        self.assertEqual(self.service.list_tickets(user_id="user-3"), [])

    def test_list_tickets_filters_by_source_app_and_status(self):
        self.service.create_ticket(user_id="user-1", source_app="certifications", subject=None, body="a")
        self.service.create_ticket(user_id="user-1", source_app="hippocampus", subject=None, body="b")

        self.assertEqual(len(self.service.list_tickets(user_id="user-1", source_app="hippocampus")), 1)
        self.assertEqual(len(self.service.list_tickets(user_id="user-1", status="closed")), 0)
        self.assertEqual(len(self.service.list_tickets(user_id="user-1", status="open")), 2)

    def test_get_ticket_rejects_a_caller_who_does_not_own_it(self):
        ticket = self.service.create_ticket(user_id="user-1", source_app="certifications", subject=None, body="a")
        with self.assertRaises(SupportTicketNotFoundError):
            self.service.get_ticket(ticket_id=ticket["id"], user_id="someone-else")

    def test_get_ticket_rejects_an_unknown_ticket_id(self):
        with self.assertRaises(SupportTicketNotFoundError):
            self.service.get_ticket(ticket_id="does-not-exist", user_id="user-1")

    def test_post_message_appends_to_the_thread(self):
        ticket = self.service.create_ticket(user_id="user-1", source_app="certifications", subject=None, body="a")
        self.service.post_message(ticket_id=ticket["id"], user_id="user-1", body="follow up")
        full = self.service.get_ticket(ticket_id=ticket["id"], user_id="user-1")
        self.assertEqual(len(full["messages"]), 2)
        self.assertEqual(full["messages"][1]["body"], "follow up")

    def test_post_message_rejects_a_caller_who_does_not_own_the_ticket(self):
        ticket = self.service.create_ticket(user_id="user-1", source_app="certifications", subject=None, body="a")
        with self.assertRaises(SupportTicketNotFoundError):
            self.service.post_message(ticket_id=ticket["id"], user_id="someone-else", body="nope")

    def test_mark_ticket_read_flips_every_unread_message(self):
        ticket = self.service.create_ticket(user_id="user-1", source_app="certifications", subject=None, body="a")
        self.service.post_message(ticket_id=ticket["id"], user_id="user-1", body="b")

        changed = self.service.mark_ticket_read(ticket_id=ticket["id"], user_id="user-1")

        self.assertEqual(changed, 2)
        full = self.service.get_ticket(ticket_id=ticket["id"], user_id="user-1")
        self.assertTrue(all(m["read"] for m in full["messages"]))
        # Idempotent: nothing left unread to flip on a second call.
        self.assertEqual(self.service.mark_ticket_read(ticket_id=ticket["id"], user_id="user-1"), 0)

    def test_mark_message_read_targets_a_single_message(self):
        ticket = self.service.create_ticket(user_id="user-1", source_app="certifications", subject=None, body="a")
        message_id = ticket["messages"][0]["id"]

        self.assertTrue(
            self.service.mark_message_read(ticket_id=ticket["id"], user_id="user-1", message_id=message_id)
        )
        self.assertFalse(
            self.service.mark_message_read(ticket_id=ticket["id"], user_id="user-1", message_id="missing")
        )

    def test_couchdb_outage_never_loses_the_ticket_only_its_messages(self):
        """Mirrors hippocampus's own resilience principle: PostgreSQL stays
        authoritative even when the document store cannot be reached."""

        class _AlwaysDownStore(InMemorySupportTicketDocumentStore):
            def put(self, ticket_id, document):
                return False

            def get(self, ticket_id):
                return None

            @property
            def available(self):
                return False

        service = SupportTicketService(
            db_adapter=DBAdapter(engine=self.engine), document_store=_AlwaysDownStore()
        )
        ticket = service.create_ticket(user_id="user-1", source_app="certifications", subject=None, body="a")

        fetched = service.get_ticket(ticket_id=ticket["id"], user_id="user-1")
        self.assertEqual(fetched["id"], ticket["id"])
        self.assertEqual(fetched["status"], "open")
        self.assertEqual(fetched["messages"], [])
        self.assertFalse(fetched["messages_available"])


if __name__ == "__main__":
    unittest.main()
