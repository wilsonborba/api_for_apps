from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Kept intentionally small (issue #17 only asks for a status column, not a
# state machine). "open" is the only status this API assigns itself; the
# others exist so a future admin view has somewhere to put a ticket without
# a schema change.
SUPPORT_TICKET_STATUSES: tuple[str, ...] = ("open", "pending", "resolved", "closed")
DEFAULT_SUPPORT_TICKET_STATUS = "open"


class SupportTicketIndexModel(BaseModel):
    """Row shape of the defaultdb_support_ticket Postgres index table.

    PostgreSQL remains authoritative for a ticket's existence, ownership,
    source_app and status. The id doubles as the CouchDB document's own
    _id (see SupportTicketDocumentModel), so a missing document never means
    a missing ticket, only that its message thread is temporarily
    unavailable.
    """

    id: str
    user_id: str
    source_app: str
    status: str = DEFAULT_SUPPORT_TICKET_STATUS
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SupportMessageModel(BaseModel):
    id: str
    sender: str
    body: str
    attachment_reference: Optional[str] = None
    timestamp: str
    read: bool = False


class SupportTicketDocumentModel(BaseModel):
    """Shape of the CouchDB document holding a ticket's full message thread."""

    ticket_id: str
    subject: Optional[str] = None
    messages: List[SupportMessageModel] = Field(default_factory=list)
    # Free-form slot for future per-app needs with no schema migration.
    extra: Dict[str, Any] = Field(default_factory=dict)
