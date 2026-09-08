from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from src.core.logs import warning
from src.core.settings import Settings, app_settings


class TelemetryDocumentStore(ABC):
    """CouchDB document store for client-side errors and telemetry logs."""

    @abstractmethod
    def put(self, error_id: str, document: dict[str, Any]) -> bool: ...

    @abstractmethod
    def get(self, error_id: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def list_recent(self, limit: int = 50, skip: int = 0) -> List[dict[str, Any]]: ...

    @property
    @abstractmethod
    def available(self) -> bool: ...


class InMemoryTelemetryDocumentStore(TelemetryDocumentStore):
    """In-memory fallback when CouchDB is unavailable."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def put(self, error_id: str, document: dict[str, Any]) -> bool:
        self._docs[error_id] = document
        return True

    def get(self, error_id: str) -> Optional[dict[str, Any]]:
        return self._docs.get(error_id)

    def list_recent(self, limit: int = 50, skip: int = 0) -> List[dict[str, Any]]:
        items = list(self._docs.values())
        items.reverse()
        return items[skip : skip + limit]

    @property
    def available(self) -> bool:
        return True


class CouchDBTelemetryDocumentStore(TelemetryDocumentStore):
    """Talks to CouchDB plain REST API for client errors."""

    def __init__(
        self,
        base_url: str,
        database: str,
        auth: Optional[tuple[str, str]] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._database = database
        self._auth = auth
        self._timeout = timeout

    def _doc_url(self, error_id: str) -> str:
        return f"{self._base_url}/{self._database}/error:{error_id}"

    def put(self, error_id: str, document: dict[str, Any]) -> bool:
        try:
            with httpx.Client(timeout=self._timeout, auth=self._auth) as client:
                existing_rev = self._get_rev(client, error_id)
                payload = dict(document)
                payload["_id"] = f"error:{error_id}"
                payload["error_id"] = error_id
                if existing_rev:
                    payload["_rev"] = existing_rev
                response = client.put(self._doc_url(error_id), json=payload)
                response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            warning(f"CouchDB put failed for error_id={error_id!r}: {exc}")
            return False

    def get(self, error_id: str) -> Optional[dict[str, Any]]:
        try:
            with httpx.Client(timeout=self._timeout, auth=self._auth) as client:
                response = client.get(self._doc_url(error_id))
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            warning(f"CouchDB get failed for error_id={error_id!r}: {exc}")
            return None

    def list_recent(self, limit: int = 50, skip: int = 0) -> List[dict[str, Any]]:
        try:
            with httpx.Client(timeout=self._timeout, auth=self._auth) as client:
                url = f"{self._base_url}/{self._database}/_all_docs"
                params = {
                    "include_docs": "true",
                    "limit": limit,
                    "skip": skip,
                    "descending": "true",
                }
                response = client.get(url, params=params)
                if response.status_code != 200:
                    return []
                data = response.json()
                rows = data.get("rows", [])
                docs = [r["doc"] for r in rows if "doc" in r and not r.get("id", "").startswith("_design/")]
                return docs
        except httpx.HTTPError as exc:
            warning(f"CouchDB list_recent failed: {exc}")
            return []

    def _get_rev(self, client: httpx.Client, error_id: str) -> Optional[str]:
        response = client.head(self._doc_url(error_id))
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


def build_telemetry_document_store(settings: Optional[Settings] = None) -> TelemetryDocumentStore:
    settings = settings or app_settings()
    couch_url = settings.TELEMETRY_COUCHDB_URL or settings.SUPPORT_COUCHDB_URL
    if not couch_url:
        return InMemoryTelemetryDocumentStore()
    username = settings.TELEMETRY_COUCHDB_USERNAME or settings.SUPPORT_COUCHDB_USERNAME
    password = settings.TELEMETRY_COUCHDB_PASSWORD or settings.SUPPORT_COUCHDB_PASSWORD
    auth = None
    if username and password:
        auth = (username, password)
    store = CouchDBTelemetryDocumentStore(
        base_url=couch_url,
        database=settings.TELEMETRY_COUCHDB_DATABASE,
        auth=auth,
    )
    if not store.available:
        warning(
            f"CouchDB unavailable at {couch_url} for database {settings.TELEMETRY_COUCHDB_DATABASE}; "
            "using in-memory telemetry document store"
        )
        return InMemoryTelemetryDocumentStore()
    return store
