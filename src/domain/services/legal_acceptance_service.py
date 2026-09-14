from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.core.settings import app_settings
from src.dal.local.db_adapter import DBAdapter


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvalidLegalDocumentTypeError(ValueError):
    pass


class LegalAcceptanceService:
    """Shared ToS/Privacy Policy acceptance state (issue #29).

    One row per (user_uuid_id, document_type) in defaultdb_legal_acceptance,
    upserted whenever the user (re-)accepts. settings.LEGAL_DOCUMENT_VERSIONS
    is the single source of truth for the current version of each document:
    an acceptance whose stored version does not match the current one counts
    as not accepted, without ever deleting the audit row, so bumping that
    setting is how a content change forces re-acceptance.
    """

    _table_name = "defaultdb_legal_acceptance"

    def __init__(self, db_adapter: Optional[DBAdapter] = None):
        self.settings = app_settings()
        self.db_adapter = db_adapter or DBAdapter()

    # ---------- internal helpers ----------

    def _document_versions(self) -> Dict[str, str]:
        return self.settings.LEGAL_DOCUMENT_VERSIONS

    def _require_known_document_type(self, document_type: str) -> str:
        versions = self._document_versions()
        if document_type not in versions:
            raise InvalidLegalDocumentTypeError(
                f"Unknown document_type. Expected one of {sorted(versions)}."
            )
        return document_type

    def _find_row(self, user_uuid_id: str, document_type: str) -> Optional[Dict[str, Any]]:
        rows = self.db_adapter.read_all(self._table_name)
        for row in rows:
            if row.get("user_uuid_id") == user_uuid_id and row.get("document_type") == document_type:
                return row
        return None

    @staticmethod
    def _entry_from_row(row: Optional[Dict[str, Any]], current_version: str) -> Dict[str, Any]:
        stored_version = row.get("version") if row else None
        accepted_at = row.get("accepted_at") if row else None
        return {
            "accepted": bool(row) and stored_version == current_version,
            "version": stored_version,
            "accepted_at": accepted_at,
            "current_version": current_version,
        }

    # ---------- public API ----------

    def get_status(self, user_uuid_id: str) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for document_type, current_version in self._document_versions().items():
            row = self._find_row(user_uuid_id, document_type)
            result[document_type] = self._entry_from_row(row, current_version)
        return result

    def accept(self, user_uuid_id: str, document_type: str) -> Dict[str, Any]:
        document_type = self._require_known_document_type(document_type)
        current_version = self._document_versions()[document_type]
        now = _utc_now()
        existing = self._find_row(user_uuid_id, document_type)
        if existing:
            self.db_adapter.update_row(
                self._table_name,
                existing["id"],
                {"version": current_version, "accepted_at": now},
            )
        else:
            self.db_adapter.insert_row(
                self._table_name,
                {
                    "id": str(uuid.uuid4()),
                    "user_uuid_id": user_uuid_id,
                    "document_type": document_type,
                    "version": current_version,
                    "accepted_at": now,
                },
            )
        row = self._find_row(user_uuid_id, document_type)
        return self._entry_from_row(row, current_version)
