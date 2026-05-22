"""
Admin CLI — destructive operations.

`reset-graph` clears every row tied to a user's life-data (memories,
entities, artifacts, conversations) so you can start clean. It does
NOT touch identity (users, auth sessions, mcp tokens, avatars) or the
admin/security audit log, so you stay signed in and your existing MCP
tokens keep working.

Run via the Makefile (which adds a `confirm=YES` safety gate):

    make reset-graph confirm=YES

Or directly inside the api container:

    docker compose exec -T api python -m reflections.admin.cli reset-graph --yes
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys

import sqlalchemy as sa

from reflections.core.db import database_manager


# Defensive: WIPE_TABLES is a hardcoded constant today, but if a future
# contributor wires it to config or a request param, an interpolated table
# name would become straight SQL injection. Enforce the shape we expect.
_SAFE_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


# Order doesn't matter — TRUNCATE … CASCADE handles FKs — but listing
# the dependent tables first keeps `pg_class` happy on older Postgres
# without CASCADE and makes the intent obvious.
WIPE_TABLES: list[str] = [
    # links first
    "memory_entity_links",
    "artifact_entity_links",
    # then the primary objects
    "memory_items",
    "entities",
    "artifacts",
    "artifact_extraction_policies",
    "volumes",
    # conversation history
    "conversation_turns",
    "conversations",
]


# These are preserved and only listed here so the help text stays
# accurate when someone reads the source.
PRESERVED_TABLES: list[str] = [
    "users",
    "sessions",        # auth cookies — keep so you don't get logged out
    "mcp_tokens",
    "avatars",
    "outbound_audit_log",
    "satellite_tokens",
    "alembic_version",
]


async def _reset() -> int:
    for t in WIPE_TABLES:
        if not _SAFE_TABLE_NAME.fullmatch(t):
            raise ValueError(f"unsafe table name in WIPE_TABLES: {t!r}")
    await database_manager.initialize()
    async with database_manager.session() as session:
        # Pre-flight: confirm every table exists. Better to fail loudly
        # here than to half-truncate.
        existing = {
            row[0]
            for row in (
                await session.execute(
                    sa.text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public'"
                    )
                )
            ).all()
        }
        missing = [t for t in WIPE_TABLES if t not in existing]
        if missing:
            print(
                f"error: expected tables not found: {missing!r}",
                file=sys.stderr,
            )
            return 2

        # Count what we're about to delete (for the summary).
        counts: dict[str, int] = {}
        for t in WIPE_TABLES:
            n = (
                await session.execute(sa.text(f"SELECT COUNT(*) FROM {t}"))
            ).scalar_one()
            counts[t] = int(n)

        # Single TRUNCATE so everything goes in one transaction. CASCADE
        # is defensive in case any FK is added later that we forget here.
        joined = ", ".join(WIPE_TABLES)
        await session.execute(
            sa.text(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")
        )
        await session.commit()

    print("Graph data reset. Deleted:", file=sys.stderr)
    width = max(len(t) for t in counts)
    for t in WIPE_TABLES:
        print(f"  {t.ljust(width)}  {counts[t]:>8d}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Preserved (untouched):", file=sys.stderr)
    for t in PRESERVED_TABLES:
        print(f"  {t}", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="reflections.admin.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser(
        "reset-graph",
        help=(
            "Truncate all memory + entity + artifact + conversation rows. "
            "Keeps users, auth, mcp tokens, avatars, and the admin audit log."
        ),
    )
    r.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation prompt.",
    )
    args = p.parse_args()

    if args.cmd == "reset-graph":
        if not args.yes:
            print(
                "This will permanently delete ALL memories, entities, "
                "artifacts, volumes, extraction policies, and conversations.",
                file=sys.stderr,
            )
            print(
                "Users, auth sessions, MCP tokens, and avatars are preserved.",
                file=sys.stderr,
            )
            reply = input("Type 'YES' to confirm: ").strip()
            if reply != "YES":
                print("aborted", file=sys.stderr)
                return 2
        return asyncio.run(_reset())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
