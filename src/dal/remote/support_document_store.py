from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from src.core.logs import warning
from src.core.settings import Settings, app_settings


class SupportTicketDocumentStore(ABC):
    """Durable, flexible support-ticket thread content.

    Modeled directly on hippocampus's own lib/dal/remote/document_store.py:
    CouchDB is the intended backend; when it's unset or unreachable, callers
    degrade to an in-memory store rather than fail. PostgreSQL's own
    defaultdb_support_ticket index remains authoritative for a ticket's
    existence, ownership and status: a missing document never means a
    missing ticket, only that its message thread is temporarily
    unavailable.
    """

    @abstractmethod
    def put(self, ticket_id: str, document: dict[str, Any]) -> bool: ...

    @abstractmethod
    def get(self, ticket_id: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def delete(self, ticket_id: str) -> bool: ...

    @property
    @abstractmethod
    def available(self) -> bool: ...


class InMemorySupportTicketDocumentStore(SupportTicketDocumentStore):
    """Default when CouchDB is unset or unreachable. See
    CouchDBSupportTicketDocumentStore for the real adapter."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def put(self, ticket_id: str, document: dict[str, Any]) -> bool:
        self._docs[ticket_id] = document
        return True

    def get(self, ticket_id: str) -> Optional[dict[str, Any]]:
        return self._docs.get(ticket_id)

    def delete(self, ticket_id: str) -> bool:
        return self._docs.pop(ticket_id, None) is not None

    @property
    def available(self) -> bool:
        return True


class CouchDBSupportTicketDocumentStore(SupportTicketDocumentStore):
    """Talks to CouchDB's plain REST API directly (PUT/GET/DELETE per doc id),
    same as hippocampus's adapter: no SDK dependency needed for something
    this small. `_rev` handling stays internal here; callers never see or
    manage CouchDB revisions."""

    def __init__(
        self, base_url: str, database: str, auth: Optional[tuple[str, str]] = None, timeout: float = 10.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._database = database
        self._auth = auth
        self._timeout = timeout

    def _doc_url(self, ticket_id: str) -> str:
        return f"{self._base_url}/{self._database}/ticket:{ticket_id}"

    def put(self, ticket_id: str, document: dict[str, Any]) -> bool:
        try:
            with httpx.Client(timeout=self._timeout, auth=self._auth) as client:
                existing_rev = self._get_rev(client, ticket_id)
                payload = dict(document)
                payload["_id"] = f"ticket:{ticket_id}"
                payload["ticket_id"] = ticket_id
                if existing_rev:
                    payload["_rev"] = existing_rev
                response = client.put(self._doc_url(ticket_id), json=payload)
                response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            warning(f"CouchDB put failed for ticket_id={ticket_id!r}: {exc}")
            return False

    def get(self, ticket_id: str) -> Optional[dict[str, Any]]:
        try:
            with httpx.Client(timeout=self._timeout, auth=self._auth) as client:
                response = client.get(self._doc_url(ticket_id))
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            warning(f"CouchDB get failed for ticket_id={ticket_id!r}: {exc}")
            return None

    def delete(self, ticket_id: str) -> bool:
        try:
            with httpx.Client(timeout=self._timeout, auth=self._auth) as client:
                rev = self._get_rev(client, ticket_id)
                if rev is None:
                    return False
                response = client.delete(self._doc_url(ticket_id), params={"rev": rev})
                response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            warning(f"CouchDB delete failed for ticket_id={ticket_id!r}: {exc}")
            return False

    def _get_rev(self, client: httpx.Client, ticket_id: str) -> Optional[str]:
        response = client.head(self._doc_url(ticket_id))
        if response.status_code == 404:
            return None
        etag = response.headers.get("ETag")
        return etag.strip('"') if etag else None

    @property
    def available(self) -> bool:
        try:
            with httpx.Client(timeout=self._timeout, auth=self._auth) as client:
                response = client.get(f"{self._base_url}/{self._database}")
                return response.status_code == 200
        except httpx.HTTPError:
            return False


def build_support_document_store(settings: Optional[Settings] = None) -> SupportTicketDocumentStore:
    settings = settings or app_settings()
    if not settings.SUPPORT_COUCHDB_URL:
        return InMemorySupportTicketDocumentStore()
    auth = None
    if settings.SUPPORT_COUCHDB_USERNAME and settings.SUPPORT_COUCHDB_PASSWORD:
        auth = (settings.SUPPORT_COUCHDB_USERNAME, settings.SUPPORT_COUCHDB_PASSWORD)
    store = CouchDBSupportTicketDocumentStore(
        base_url=settings.SUPPORT_COUCHDB_URL,
        database=settings.SUPPORT_COUCHDB_DATABASE,
        auth=auth,
    )
    if not store.available:
        warning(
            f"CouchDB unavailable at {settings.SUPPORT_COUCHDB_URL}; "
            "using in-memory support ticket document store"
        )
        return InMemorySupportTicketDocumentStore()
    return store
