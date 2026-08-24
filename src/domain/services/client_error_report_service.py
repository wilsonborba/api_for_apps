import json

from src.dal.local.db_adapter import DBAdapter


class ClientErrorReportService:
    _table_name = "defaultdb_client_error_report"

    def __init__(self):
        self.db_adapter = DBAdapter()

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
