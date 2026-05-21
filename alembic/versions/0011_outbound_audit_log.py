"""outbound_audit_log

Revision ID: 0011_outbound_audit_log
Revises: 0010_mcp_tokens
Create Date: 2026-05-21

Audit trail for every outbound HTTP call made on behalf of a user. Recorded
even when the call is denied (non-admin attempt) so admins can see who tried
to reach what.
"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0011_outbound_audit_log"
down_revision = "0010_mcp_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbound_audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        # Caller-supplied tag (e.g. "internet_search", "calendar_sync"). Helps
        # group by feature when auditing.
        sa.Column("purpose", sa.Text(), nullable=True),
        # Final HTTP status from the upstream call. NULL when the call was
        # denied (no request was actually made).
        sa.Column("status_code", sa.Integer(), nullable=True),
        # "ok" | "denied" | "error"
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "outbound_audit_log_user_ts_idx",
        "outbound_audit_log",
        ["user_id", "ts"],
        unique=False,
    )
    op.create_index(
        "outbound_audit_log_outcome_idx",
        "outbound_audit_log",
        ["outcome", "ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("outbound_audit_log_outcome_idx", table_name="outbound_audit_log")
    op.drop_index("outbound_audit_log_user_ts_idx", table_name="outbound_audit_log")
    op.drop_table("outbound_audit_log")
