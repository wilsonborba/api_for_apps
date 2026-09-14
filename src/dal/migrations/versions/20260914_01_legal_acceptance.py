"""Create the defaultdb_legal_acceptance table (issue #29).

Shared ToS/Privacy Policy acceptance state across the whole Asodya
ecosystem: the canonical documents live on the domain frontend, but any
subproject asks api_for_apps whether the current user has accepted them.
One row per (user_uuid_id, document_type), upserted whenever the user
(re-)accepts; settings.LEGAL_DOCUMENT_VERSIONS is the single source of
truth for what the current version of each document is.

Revision ID: 20260914_01
Revises: 20260909_01
"""
from alembic import op
import sqlalchemy as sa


revision = "20260914_01"
down_revision = "20260909_01"
branch_labels = None
depends_on = None

_TABLE = "defaultdb_legal_acceptance"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        op.create_table(
            _TABLE,
            # as_uuid=False: reads back as a plain string, matching this
            # repo's existing identifier convention (see defaultdb_user.uuid_id
            # and defaultdb_support_ticket.id).
            sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column("user_uuid_id", sa.String(length=64), nullable=False),
            sa.Column("document_type", sa.String(length=50), nullable=False),
            sa.Column("version", sa.String(length=50), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_uuid_id", "document_type", name=f"uq_{_TABLE}_user_document"),
        )
        op.create_index(f"ix_{_TABLE}_user_uuid_id", _TABLE, ["user_uuid_id"])


def downgrade() -> None:
    op.drop_index(f"ix_{_TABLE}_user_uuid_id", table_name=_TABLE)
    op.drop_table(_TABLE)
