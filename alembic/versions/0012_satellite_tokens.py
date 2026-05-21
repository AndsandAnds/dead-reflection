"""satellite_tokens (scaffold)

Revision ID: 0012_satellite_tokens
Revises: 0011_outbound_audit_log
Create Date: 2026-05-21

Scaffolded for the voice-satellite protocol (see docs/voice-satellite-
protocol.md). The mint/list/revoke REST + CLI surface lands in v2 along
with the first reference satellite (Pi + ReSpeaker). The table is added
now so the schema doesn't churn when we get there.

Mirrors mcp_tokens shape; the only addition is `capabilities` JSONB so
satellites can advertise mic / speaker / sample rate / local-VAD support
on the initial WS hello and the server can persist that profile.
"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0012_satellite_tokens"
down_revision = "0011_outbound_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "satellite_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Human label so the user can identify devices ("kitchen Pi",
        # "garage ESP32", "ex-Google-Home satellite").
        sa.Column("name", sa.Text(), nullable=False),
        # SHA-256 hash of the raw token. Raw is shown to the user exactly
        # once at mint time.
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        # Free-form per-device profile populated from the WS `hello`:
        # {has_mic, has_speaker, sample_rate, vad_local, model, fw_version}
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "satellite_tokens_user_idx",
        "satellite_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "satellite_tokens_token_hash_unique",
        "satellite_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "satellite_tokens_active_lookup_idx",
        "satellite_tokens",
        ["token_hash", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "satellite_tokens_active_lookup_idx", table_name="satellite_tokens"
    )
    op.drop_index(
        "satellite_tokens_token_hash_unique", table_name="satellite_tokens"
    )
    op.drop_index("satellite_tokens_user_idx", table_name="satellite_tokens")
    op.drop_table("satellite_tokens")
