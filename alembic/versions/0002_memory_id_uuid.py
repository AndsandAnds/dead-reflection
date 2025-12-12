"""memory_items.id to UUID

Revision ID: 0002_memory_id_uuid
Revises: 0001_memory_vector_tables
Create Date: 2025-12-12
"""

from __future__ import annotations

from alembic import op

revision = "0002_memory_id_uuid"
down_revision = "0001_memory_vector_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert id from text -> uuid (UUIDv7 string values are valid UUIDs).
    op.execute("ALTER TABLE memory_items ALTER COLUMN id TYPE uuid USING id::uuid;")


def downgrade() -> None:
    op.execute("ALTER TABLE memory_items ALTER COLUMN id TYPE text USING id::text;")
