"""artifact + memory privacy flags + extraction policies

Revision ID: 0014_artifact_privacy_policies
Revises: 0013_artifacts
Create Date: 2026-05-21

Two related changes that together let a user say "extract these PDFs
into the catalog, but DON'T let Claude Desktop see their contents":

  - artifacts.private + memory_items.private: a row-level flag that
    excludes content from MCP recall responses unless the caller's
    token has the `mcp:read_private` scope. Web UI (session cookie)
    still shows them.
  - artifact_extraction_policies: per-(volume, glob, mime) rules that
    drive `apply_extraction_policies`. Action is one of
    `extract` (public), `extract_private`, or `ignore` (skip).

The mcp_tokens.scopes column already exists (JSON, since migration
0010); this commit just standardizes on `mcp:read`, `mcp:write`, and
the new opt-in `mcp:read_private` in the token verifier.
"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0014_artifact_privacy_policies"
down_revision = "0013_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- privacy flags ----------------------------------------------------
    op.add_column(
        "artifacts",
        sa.Column(
            "private",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "memory_items",
        sa.Column(
            "private",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # We filter on private all the time on the recall path. Partial index
    # over (user_id) WHERE NOT private is the hot path; the equality
    # predicate combines with the existing user_id filter cheaply.
    op.create_index(
        "memory_items_user_public_idx",
        "memory_items",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("private = false"),
    )

    # --- extraction policies ---------------------------------------------
    # Order matters: first matching rule wins. The `position` column lets
    # the UI/MCP reorder without churning ids.
    op.create_table(
        "artifact_extraction_policies",
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
        sa.Column("position", sa.Integer(), nullable=False),
        # Glob (e.g. "Photos/2024/*.jpg") evaluated against `relative_path`.
        # NULL means "match anything".
        sa.Column("glob_pattern", sa.Text(), nullable=True),
        # Mime prefix match (e.g. "image/" matches image/jpeg + image/png).
        # NULL means "any mime".
        sa.Column("mime_prefix", sa.Text(), nullable=True),
        # Kind exact match (pdf|image|audio|video|other). NULL = any.
        sa.Column("kind", sa.Text(), nullable=True),
        # Action: extract | extract_private | ignore.
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "artifact_extraction_policies_volume_position_idx",
        "artifact_extraction_policies",
        ["volume_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "artifact_extraction_policies_volume_position_idx",
        table_name="artifact_extraction_policies",
    )
    op.drop_table("artifact_extraction_policies")
    op.drop_index(
        "memory_items_user_public_idx", table_name="memory_items"
    )
    op.drop_column("memory_items", "private")
    op.drop_column("artifacts", "private")
