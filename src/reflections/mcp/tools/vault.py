"""MCP tool for exporting the user's vault to a file path."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import Field

from reflections.core.db import database_manager
from reflections.mcp.auth import current_user_id
from reflections.vault.service import VaultService

_vault: VaultService | None = None


def _service() -> VaultService:
    global _vault
    if _vault is None:
        _vault = VaultService.default()
    return _vault


def register(mcp) -> None:  # type: ignore[no-untyped-def]
    @mcp.tool
    async def export_vault(
        target_path: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Absolute path on the host where the tar.gz should be "
                    "written. The api container sees the host filesystem at "
                    "/app (the bind-mount root); use a path under /app if "
                    "calling from MCP-over-HTTP and you want the file to "
                    "land in the project directory."
                ),
            ),
        ],
    ) -> dict:
        """
        Export every memory + entity for the authenticated user to a markdown
        vault, packaged as a tar.gz at `target_path`.

        Returns: {path, daily_notes, entity_notes, memories, entities, bytes}.

        The DB stays canonical; the export is a one-way snapshot intended for
        backup, grep, Obsidian, or piping into git. Use `import_vault` to
        push edits back in.
        """
        uid = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            blob, stats = await _service().export_user_vault(
                session, user_id=uid
            )
        target = Path(target_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        return {
            "path": str(target),
            "bytes": len(blob),
            "daily_notes": stats.daily_notes,
            "entity_notes": stats.entity_notes,
            "memories": stats.memories,
            "entities": stats.entities,
        }

    @mcp.tool
    async def import_vault(
        source_path: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Absolute path to a tar.gz produced by `export_vault` "
                    "(possibly with edits applied in Obsidian or any editor)."
                ),
            ),
        ],
        dry_run: bool = False,
    ) -> dict:
        """
        Apply edits from a vault archive: updates existing memories' content
        (re-embeds them) and existing entities' descriptions. NEW rows in
        the archive are skipped — the DB stays canonical for what exists.

        Returns: {memories_updated, memories_reembedded, entities_updated,
        skipped, errors}.
        """
        uid = current_user_id()
        source = Path(source_path).expanduser()
        if not source.exists():
            return {"error": "source_not_found", "path": str(source)}
        blob = source.read_bytes()
        await database_manager.initialize()
        async with database_manager.session() as session:
            stats = await _service().import_user_vault(
                session, user_id=uid, tarball=blob, dry_run=dry_run
            )
        return stats.model_dump(mode="json")
