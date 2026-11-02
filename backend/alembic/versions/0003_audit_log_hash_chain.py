"""add audit log hash chain columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("entry_hash", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_audit_logs_entry_hash"), "audit_logs", ["entry_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_entry_hash"), table_name="audit_logs")
    op.drop_column("audit_logs", "entry_hash")
    op.drop_column("audit_logs", "prev_hash")
