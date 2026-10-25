"""Drop legacy defaultdb_client_error_report table.

Client errors are now exclusively ingested into CouchDB via the
/apps/api/v1/client-errors telemetry pipeline.

Revision ID: 20260909_01
Revises: 20260830_01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260909_01"
down_revision = "20260830_01"
branch_labels = None
depends_on = None

_TABLE = "defaultdb_client_error_report"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        op.drop_table(_TABLE)


def downgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_name", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("route", sa.String()),
        sa.Column("error_title", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=False),
        sa.Column("error_code", sa.String()),
        sa.Column("details_json", postgresql.JSONB()),
        sa.Column("user_agent", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
