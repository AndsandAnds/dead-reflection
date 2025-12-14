"""avatars table + users.active_avatar_id

Revision ID: 0006_avatars_and_active_avatar
Revises: 0005_auth_user_name
Create Date: 2025-12-14
"""

from __future__ import annotations

import sqlalchemy as sa  # type: ignore[import-not-found]

from alembic import op

revision = "0006_avatars_and_active_avatar"
down_revision = "0005_auth_user_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatars",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("persona_prompt", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("voice_config", sa.JSON(), nullable=True),
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
    op.create_index("avatars_user_id_idx", "avatars", ["user_id"], unique=False)

    op.add_column("users", sa.Column("active_avatar_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "users_active_avatar_fk",
        "users",
        "avatars",
        ["active_avatar_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("users_active_avatar_fk", "users", type_="foreignkey")
    op.drop_column("users", "active_avatar_id")

    op.drop_index("avatars_user_id_idx", table_name="avatars")
    op.drop_table("avatars")


