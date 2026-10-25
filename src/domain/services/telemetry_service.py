from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.logs import error, warning
from src.core.settings import app_settings
from src.dal.local.redis_adapter import RedisAdapter
from src.dal.remote.telemetry_document_store import (
    TelemetryDocumentStore,
    build_telemetry_document_store,
)
from src.domain.models.telemetry_model import ClientErrorPayload


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TelemetryService:
    """Ingests client errors and persists them in CouchDB, with Redis rate-limiting."""

    def __init__(
        self,
        document_store: Optional[TelemetryDocumentStore] = None,
    ):
        self.settings = app_settings()
        self.document_store = document_store or build_telemetry_document_store(self.settings)

    async def check_rate_limit(
        self,
        adapter: RedisAdapter,
        client_ip: str,
        limit: int = 10,
        window_seconds: int = 60,
    ) -> bool:
        """Returns True if within rate limit, False if exceeded."""
        key = adapter.k("ratelimit:telemetry", client_ip)
        try:
            current = await adapter.incr(key, amount=1)
            if current == 1:
                await adapter.expire(key, window_seconds)
            return current <= limit
        except Exception as exc:
            warning(f"Redis rate limit check failed: {exc}")
            return True

    def record_client_error(
        self,
        payload: ClientErrorPayload,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Persists the error in CouchDB."""
        error_id = str(uuid.uuid4())
        server_ts = _utc_now_iso()

        doc: Dict[str, Any] = {
            "error_id": error_id,
            "app_name": payload.app_name,
            "app_version": payload.app_version,
            "environment": payload.environment,
            "route": payload.route,
            "error_title": payload.error_title,
            "error_message": payload.error_message,
            "error_code": payload.error_code,
            "stack_trace": payload.stack_trace,
            "request_id": payload.request_id,
            "user_id": user_id,
            "session_id": session_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "client_timestamp": payload.client_timestamp,
            "server_timestamp": server_ts,
            "details": payload.details,
            "extra": payload.extra,
        }

        success = self.document_store.put(error_id, doc)
        if not success:
            warning(f"Failed to persist client error {error_id} to document store.")

        return error_id

    def get_error(self, error_id: str) -> Optional[Dict[str, Any]]:
        return self.document_store.get(error_id)

    def list_errors(self, limit: int = 50, skip: int = 0) -> List[Dict[str, Any]]:
        return self.document_store.list_recent(limit=limit, skip=skip)
