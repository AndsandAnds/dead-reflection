"""memory_items content tsvector + GIN index

Revision ID: 0015_memory_content_tsv
Revises: 0014_artifact_privacy_policies
Create Date: 2026-05-22

Adds a generated-stored `content_tsv` column to memory_items so the recall
path can fuse BM25 (Postgres tsvector / ts_rank_cd) with the existing
pgvector inner-product ranking via Reciprocal Rank Fusion. Generated
columns auto-maintain on insert/update so no trigger or backfill is needed.
"""

from __future__ import annotations

from alembic import op

revision = "0015_memory_content_tsv"
down_revision = "0014_artifact_privacy_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE memory_items "
        "ADD COLUMN content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS memory_items_content_tsv_gin "
        "ON memory_items USING GIN (content_tsv);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS memory_items_content_tsv_gin;")
    op.execute("ALTER TABLE memory_items DROP COLUMN IF EXISTS content_tsv;")
