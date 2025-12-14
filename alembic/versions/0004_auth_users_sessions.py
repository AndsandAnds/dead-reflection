"""auth users + sessions

Revision ID: 0004_auth_users_sessions
Revises: 0003_memory_user_avatar_uuid
Create Date: 2025-12-14
"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0004_auth_users_sessions"
down_revision = "0003_memory_user_avatar_uuid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("users_email_unique", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Store a hash of the bearer session token (cookie holds raw token).
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
    )
    op.create_index("sessions_user_id_idx", "sessions", ["user_id"], unique=False)
    op.create_index("sessions_token_hash_unique", "sessions", ["token_hash"], unique=True)
    op.create_index(
        "sessions_active_lookup_idx",
        "sessions",
        ["token_hash", "revoked_at", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("sessions_active_lookup_idx", table_name="sessions")
    op.drop_index("sessions_token_hash_unique", table_name="sessions")
    op.drop_index("sessions_user_id_idx", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("users_email_unique", table_name="users")
    op.drop_table("users")


