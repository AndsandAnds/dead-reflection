"""auth: users.name

Revision ID: 0005_auth_user_name
Revises: 0004_auth_users_sessions
Create Date: 2025-12-14
"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0005_auth_user_name"
down_revision = "0004_auth_users_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Default to empty string so existing rows can be migrated without NULLs.
    op.add_column(
        "users",
        sa.Column(
            "name",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    # Drop the default going forward; application should set name explicitly.
    op.alter_column("users", "name", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "name")


