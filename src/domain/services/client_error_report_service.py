import json
from sqlalchemy import text

from src.dal.local.db_adapter import DBAdapter


class ClientErrorReportService:
    _table_name = "defaultdb_client_error_report"

    def __init__(self):
        self.db_adapter = DBAdapter()
        self._table_ready = False

    def _ensure_table(self) -> None:
        create_sql = text(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table_name} (
                id SERIAL PRIMARY KEY,
                app_name TEXT NOT NULL,
                environment TEXT NOT NULL,
                route TEXT NULL,
                error_title TEXT NOT NULL,
                error_message TEXT NOT NULL,
                error_code TEXT NULL,
                details_json JSONB NULL,
                user_agent TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        with self.db_adapter.connect() as conn:
            conn.execute(create_sql)
            conn.commit()

    def create_report(
        self,
        *,
        app_name: str,
        environment: str,
        route: str | None,
        error_title: str,
        error_message: str,
        error_code: str | None,
        details: dict | None,
        user_agent: str | None,
    ) -> int | None:
        if not self._table_ready:
            self._ensure_table()
            self._table_ready = True
        inserted = self.db_adapter.insert_row(
            self._table_name,
            {
                "app_name": app_name,
                "environment": environment,
                "route": route,
                "error_title": error_title,
                "error_message": error_message,
                "error_code": error_code,
                "details_json": json.dumps(details) if details is not None else None,
                "user_agent": user_agent,
            },
        )
        return inserted[0] if inserted else None
