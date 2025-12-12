"""memory_items user_id/avatar_id to UUID

Revision ID: 0003_memory_user_avatar_uuid
Revises: 0002_memory_id_uuid
Create Date: 2025-12-12
"""

from __future__ import annotations

from alembic import op

revision = "0003_memory_user_avatar_uuid"
down_revision = "0002_memory_id_uuid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE memory_items ALTER COLUMN user_id TYPE uuid USING user_id::uuid;"
    )
    op.execute(
        "ALTER TABLE memory_items ALTER COLUMN avatar_id TYPE uuid USING "
        "avatar_id::uuid;"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE memory_items ALTER COLUMN user_id TYPE text USING user_id::text;"
    )
    op.execute(
        "ALTER TABLE memory_items ALTER COLUMN avatar_id TYPE text USING "
        "avatar_id::text;"
    )
