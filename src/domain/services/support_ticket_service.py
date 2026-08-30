from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logs import warning
from src.core.settings import app_settings
from src.dal.local.db_adapter import DBAdapter
from src.dal.remote.support_document_store import (
    SupportTicketDocumentStore,
    build_support_document_store,
)
from src.domain.models.support_ticket_model import DEFAULT_SUPPORT_TICKET_STATUS


def _utc_now() -> datetime:
    """A real datetime object, not a string: the index table's created_at /
    updated_at are proper DateTime columns, and unlike Postgres, SQLite's
    DateTime bind processor rejects plain strings outright, which is exactly
    what surfaced this during local SQLite verification."""
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    """ISO string for message timestamps living inside the CouchDB document,
    a JSON field with no column type to satisfy."""
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


class SupportTicketError(Exception):
    pass


class SupportTicketNotFoundError(SupportTicketError):
    pass


class SupportTicketService:
    """Cross-app support ticket service: create/list/read/reply/mark-read.

    Polyglot storage, mirroring hippocampus's own Memory pattern (spec in
    issue #17): PostgreSQL's defaultdb_support_ticket index table is
    authoritative for a ticket's existence, ownership, source_app and
    status; CouchDB holds the full message thread and degrades gracefully
    to an in-memory store if unreachable, so a ticket is never lost, only
    its message content is momentarily unavailable.
    """

    _table_name = "defaultdb_support_ticket"

    def __init__(
        self,
        db_adapter: Optional[DBAdapter] = None,
        document_store: Optional[SupportTicketDocumentStore] = None,
    ):
        self.settings = app_settings()
        self.db_adapter = db_adapter or DBAdapter()
        self.document_store = document_store or build_support_document_store(self.settings)

    # ---------- internal helpers ----------

    def _touch_updated_at(self, ticket_id: str) -> None:
        self.db_adapter.update_row(self._table_name, ticket_id, {"updated_at": _utc_now()})

    def _require_ticket(self, ticket_id: str, user_id: str) -> Dict[str, Any]:
        ticket = self.db_adapter.read_by_id(self._table_name, ticket_id)
        if not ticket or ticket.get("user_id") != user_id:
            raise SupportTicketNotFoundError("Support ticket not found")
        return ticket

    @staticmethod
    def _new_message(*, sender: str, body: str, attachment_reference: Optional[str]) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "sender": sender,
            "body": body,
            "attachment_reference": attachment_reference,
            "timestamp": _utc_now_iso(),
            "read": False,
        }

    # ---------- public API ----------

    def create_ticket(
        self,
        *,
        user_id: str,
        source_app: str,
        subject: Optional[str],
        body: str,
        attachment_reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        ticket_id = str(uuid.uuid4())
        now = _utc_now()

        self.db_adapter.insert_row(
            self._table_name,
            {
                "id": ticket_id,
                "user_id": user_id,
                "source_app": source_app,
                "status": DEFAULT_SUPPORT_TICKET_STATUS,
                "created_at": now,
                "updated_at": now,
            },
        )

        message = self._new_message(sender="user", body=body, attachment_reference=attachment_reference)
        document = {
            "ticket_id": ticket_id,
            "subject": subject,
            "messages": [message],
            "extra": {},
        }
        if not self.document_store.put(ticket_id, document):
            warning(f"Support ticket {ticket_id} created but its opening message did not reach the document store")

        ticket = self.db_adapter.read_by_id(self._table_name, ticket_id)
        return {**ticket, "subject": subject, "messages": [message]}

    def list_tickets(
        self,
        *,
        user_id: str,
        source_app: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Tickets belonging to `user_id`, optionally filtered by source_app
        and status. Scoped to the caller: this repo has no admin/role
        authorization primitive yet, so a future cross-user admin view
        (explicitly out of scope for issue #17) will need one before it can
        widen this query past a single user's own tickets."""
        tickets = self.db_adapter.read_all(self._table_name)
        tickets = [t for t in tickets if t.get("user_id") == user_id]
        if source_app:
            tickets = [t for t in tickets if t.get("source_app") == source_app]
        if status:
            tickets = [t for t in tickets if t.get("status") == status]
        tickets.sort(key=lambda t: t.get("updated_at") or "", reverse=True)
        return tickets

    def get_ticket(self, *, ticket_id: str, user_id: str) -> Dict[str, Any]:
        ticket = self._require_ticket(ticket_id, user_id)
        document = self.document_store.get(ticket_id) or {}
        return {
            **ticket,
            "subject": document.get("subject"),
            "messages": document.get("messages", []),
            "extra": document.get("extra", {}),
            "messages_available": self.document_store.available,
        }

    def post_message(
        self,
        *,
        ticket_id: str,
        user_id: str,
        body: str,
        attachment_reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_ticket(ticket_id, user_id)
        document = self.document_store.get(ticket_id) or {
            "ticket_id": ticket_id,
            "subject": None,
            "messages": [],
            "extra": {},
        }
        message = self._new_message(sender="user", body=body, attachment_reference=attachment_reference)
        document.setdefault("messages", []).append(message)
        stored = self.document_store.put(ticket_id, document)
        self._touch_updated_at(ticket_id)
        if not stored:
            raise SupportTicketError("Support ticket message could not be stored")
        return message

    def mark_ticket_read(self, *, ticket_id: str, user_id: str) -> int:
        self._require_ticket(ticket_id, user_id)
        document = self.document_store.get(ticket_id)
        if document is None:
            return 0
        changed = 0
        for message in document.get("messages", []):
            if not message.get("read"):
                message["read"] = True
                changed += 1
        if changed:
            self.document_store.put(ticket_id, document)
            self._touch_updated_at(ticket_id)
        return changed

    def mark_message_read(self, *, ticket_id: str, user_id: str, message_id: str) -> bool:
        self._require_ticket(ticket_id, user_id)
        document = self.document_store.get(ticket_id)
        if document is None:
            return False
        for message in document.get("messages", []):
            if message.get("id") == message_id:
                if not message.get("read"):
                    message["read"] = True
                    self.document_store.put(ticket_id, document)
                    self._touch_updated_at(ticket_id)
                return True
        return False
