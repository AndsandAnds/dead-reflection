"""artifacts + volumes + links

Revision ID: 0013_artifacts
Revises: 0012_satellite_tokens
Create Date: 2026-05-21

In-place artifact catalog: the bytes live where the user keeps them
(e.g. a 10TB external drive). Postgres holds metadata + extracted
text/embeddings only. See docs/voice-satellite-protocol.md and the
companion docs/artifact-catalog.md (to be added with the catalog
bridge) for the wider design.
"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0013_artifacts"
down_revision = "0012_satellite_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- volumes ----------------------------------------------------------
    # A volume is a registered filesystem root the user wants Reflections
    # to know about. Identity survives remounts via:
    #   - volume_uuid: OS-reported (diskutil/blkid). Stable across
    #     remounts of the same physical disk.
    #   - fingerprint: a generated UUID written to
    #     <volume>/.reflections-volume.json by the catalog bridge on
    #     first registration. Belt-and-suspenders if volume_uuid changes
    #     (e.g. reformat).
    op.create_table(
        "volumes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        # Either may be NULL on volumes where we couldn't read one; at
        # least one is required at the application layer.
        sa.Column("volume_uuid", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.Text(), nullable=True),
        # Known mount points across machines:
        #   [{"host": "kestrel", "path": "/Volumes/Photos-10TB"}, ...]
        sa.Column("mount_hints", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("volumes_user_idx", "volumes", ["user_id"], unique=False)
    # Per-user uniqueness on either identifier when present. Partial
    # unique indexes keep NULLs from conflicting.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS volumes_user_volume_uuid_unique "
        "ON volumes (user_id, volume_uuid) WHERE volume_uuid IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS volumes_user_fingerprint_unique "
        "ON volumes (user_id, fingerprint) WHERE fingerprint IS NOT NULL;"
    )

    # --- artifacts --------------------------------------------------------
    # One row per file the catalog has seen. The bytes are NOT in this
    # table — they live at (volume.mount_path, relative_path) at read
    # time. catalog_state tracks the extraction lifecycle:
    #   catalogued — stat-only, no body extracted yet
    #   extracting — extractor running
    #   extracted  — derived chunks written, see memory_items.artifact_id
    #   stale      — (size,mtime) changed since last extraction
    #   failed     — extractor errored; see error
    #   offline    — volume not currently mounted (computed at query
    #                time when possible; persisted here when long-lived)
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "volume_id",
            sa.Uuid(),
            sa.ForeignKey("volumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relative_path", sa.Text(), nullable=False),
        # pdf | image | audio | video | other. Computed from mime/ext on
        # ingest; user can override.
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mtime", sa.DateTime(timezone=True), nullable=False),
        # Lazy: computed on demand (initial extraction, change check,
        # dedupe). Avoiding it lets 10TB initial catalog walks finish
        # in minutes, not hours.
        sa.Column("sha256", sa.Text(), nullable=True),
        # Free-form: EXIF, duration_s, page_count, dimensions, codec...
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("catalog_state", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
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
    # The natural key. Replays / re-catalogs upsert on this.
    op.create_index(
        "artifacts_volume_path_unique",
        "artifacts",
        ["volume_id", "relative_path"],
        unique=True,
    )
    op.create_index(
        "artifacts_user_kind_idx",
        "artifacts",
        ["user_id", "kind"],
        unique=False,
    )
    op.create_index(
        "artifacts_sha256_idx",
        "artifacts",
        ["sha256"],
        unique=False,
        postgresql_where=sa.text("sha256 IS NOT NULL"),
    )
    op.create_index(
        "artifacts_catalog_state_idx",
        "artifacts",
        ["catalog_state"],
        unique=False,
    )

    # --- artifact_entity_links --------------------------------------------
    # Mirrors memory_entity_links — same shape so the graph endpoint
    # can union edges trivially.
    op.create_table(
        "artifact_entity_links",
        sa.Column(
            "artifact_id",
            sa.Uuid(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation", sa.Text(), nullable=False, server_default=""),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "artifact_id", "entity_id", "relation",
            name="artifact_entity_links_pk",
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS artifact_entity_links_entity_idx "
        "ON artifact_entity_links (entity_id);"
    )

    # --- memory_items: source pointer back to an artifact -----------------
    # When an extractor writes a chunk derived from a PDF page / audio
    # segment / image caption, it stamps the source here so the UI can
    # render "from <title> (p.7)" and the graph can draw memory ↔
    # artifact edges.
    op.add_column(
        "memory_items",
        sa.Column(
            "artifact_id",
            sa.Uuid(),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "memory_items",
        sa.Column("artifact_locator", sa.JSON(), nullable=True),
    )
    op.create_index(
        "memory_items_artifact_id_idx",
        "memory_items",
        ["artifact_id"],
        unique=False,
        postgresql_where=sa.text("artifact_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "memory_items_artifact_id_idx", table_name="memory_items"
    )
    op.drop_column("memory_items", "artifact_locator")
    op.drop_column("memory_items", "artifact_id")

    op.execute("DROP INDEX IF EXISTS artifact_entity_links_entity_idx;")
    op.drop_table("artifact_entity_links")

    op.drop_index("artifacts_catalog_state_idx", table_name="artifacts")
    op.drop_index("artifacts_sha256_idx", table_name="artifacts")
    op.drop_index("artifacts_user_kind_idx", table_name="artifacts")
    op.drop_index("artifacts_volume_path_unique", table_name="artifacts")
    op.drop_table("artifacts")

    op.execute("DROP INDEX IF EXISTS volumes_user_fingerprint_unique;")
    op.execute("DROP INDEX IF EXISTS volumes_user_volume_uuid_unique;")
    op.drop_index("volumes_user_idx", table_name="volumes")
    op.drop_table("volumes")
