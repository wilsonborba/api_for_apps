"""Create the initial api_for_apps schema.

Revision ID: 20260824_01
Revises: None
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "defaultdb_user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("first_name", sa.String(length=255)),
        sa.Column("last_name", sa.String(length=255)),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("password", sa.Text(), nullable=False),
        sa.Column("access_level", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login", sa.DateTime(timezone=True)),
        sa.Column("date_joined", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phone_number", sa.String(length=64)),
        sa.Column("supabase_user_id", sa.String(length=36), nullable=False, unique=True),
    )
    op.create_table(
        "defaultdb_client_error_report",
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


def downgrade() -> None:
    op.drop_table("defaultdb_client_error_report")
    op.drop_table("defaultdb_user")
