"""auth: users.is_admin

Revision ID: 0008_users_is_admin
Revises: 0007_conversations
Create Date: 2026-05-21

"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0008_users_is_admin"
down_revision = "0007_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
