"""entities + memory_entity_links

Revision ID: 0009_entities
Revises: 0008_users_is_admin
Create Date: 2026-05-21

"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0009_entities"
down_revision = "0008_users_is_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # kind: person | place | event | topic
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        # Embedding column: created as text then altered to pgvector(384). Nullable
        # because entities may exist before an embedding has been computed.
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.execute(
        "ALTER TABLE entities ALTER COLUMN embedding "
        "TYPE vector(384) USING NULLIF(embedding, '')::vector;"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS entities_user_kind_slug_unique "
        "ON entities (user_id, kind, slug);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS entities_user_kind_idx "
        "ON entities (user_id, kind);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS entities_embedding_hnsw_ip "
        "ON entities USING hnsw (embedding vector_ip_ops);"
    )

    op.create_table(
        "memory_entity_links",
        sa.Column(
            "memory_item_id",
            sa.Uuid(),
            sa.ForeignKey("memory_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Empty string instead of NULL so the composite PK has a stable shape.
        sa.Column("relation", sa.Text(), nullable=False, server_default=""),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "memory_item_id", "entity_id", "relation", name="memory_entity_links_pk"
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS memory_entity_links_entity_idx "
        "ON memory_entity_links (entity_id);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS memory_entity_links_entity_idx;")
    op.drop_table("memory_entity_links")
    op.execute("DROP INDEX IF EXISTS entities_embedding_hnsw_ip;")
    op.execute("DROP INDEX IF EXISTS entities_user_kind_idx;")
    op.execute("DROP INDEX IF EXISTS entities_user_kind_slug_unique;")
    op.drop_table("entities")
