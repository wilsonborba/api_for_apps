"""Create the support_tickets index table (issue #17).

Postgres holds only the authoritative index (existence, ownership,
source_app, status). The full message thread lives in CouchDB, keyed by
this table's id, per the polyglot storage design agreed in issue #17.

Revision ID: 20260830_01
Revises: 20260824_01
"""
from alembic import op
import sqlalchemy as sa


revision = "20260830_01"
down_revision = "20260824_01"
branch_labels = None
depends_on = None

_TABLE = "defaultdb_support_ticket"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            # as_uuid=False: reads back as a plain string, matching this
            # repo's existing identifier convention (see defaultdb_user.uuid_id).
            # The column is still a native UUID type in Postgres, and it
            # doubles as the CouchDB document's own _id (no link column).
            sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("source_app", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'open'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        # The cross-app admin view (out of scope here) queries, filters and
        # sorts this table by exactly these columns.
        op.create_index(f"ix_{_TABLE}_user_id", _TABLE, ["user_id"])
        op.create_index(f"ix_{_TABLE}_source_app", _TABLE, ["source_app"])
        op.create_index(f"ix_{_TABLE}_status", _TABLE, ["status"])


def downgrade() -> None:
    op.drop_index(f"ix_{_TABLE}_status", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_source_app", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_user_id", table_name=_TABLE)
    op.drop_table(_TABLE)
