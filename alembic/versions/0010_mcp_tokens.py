"""mcp_tokens

Revision ID: 0010_mcp_tokens
Revises: 0009_entities
Create Date: 2026-05-21

"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0010_mcp_tokens"
down_revision = "0009_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Human-friendly label so users can identify tokens in a list ("Claude
        # Desktop on Macbook", "Local LM Studio", etc.).
        sa.Column("name", sa.Text(), nullable=False),
        # SHA-256 hash of the raw token; raw is shown to the user exactly once.
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        # Reserved for future per-token scoping (read-only, memory-only, etc.).
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("mcp_tokens_user_idx", "mcp_tokens", ["user_id"], unique=False)
    op.create_index(
        "mcp_tokens_token_hash_unique", "mcp_tokens", ["token_hash"], unique=True
    )
    op.create_index(
        "mcp_tokens_active_lookup_idx",
        "mcp_tokens",
        ["token_hash", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("mcp_tokens_active_lookup_idx", table_name="mcp_tokens")
    op.drop_index("mcp_tokens_token_hash_unique", table_name="mcp_tokens")
    op.drop_index("mcp_tokens_user_idx", table_name="mcp_tokens")
    op.drop_table("mcp_tokens")
