"""
Command-line tools for MCP token administration.

Run via the `make mcp-token` target so the alembic env (DB url + schema) is
already wired. Direct invocation:

    docker compose exec api python -m reflections.mcp.cli mint \
        --email you@example.com --name "Claude Desktop"
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from reflections.auth.repository import AuthRepository
from reflections.core.db import database_manager
from reflections.mcp.service import McpService


async def _mint(email: str, name: str, scopes: list[str] | None) -> int:
    await database_manager.initialize()
    async with database_manager.session() as session:
        user = await AuthRepository().get_user_by_email(session, email=email)
        if user is None:
            print(f"error: no user with email {email!r}", file=sys.stderr)
            return 2
        row, raw = await McpService.default().mint(
            session, user_id=user.id, name=name, scopes=scopes
        )
    # Stdout is the token; everything else goes to stderr so scripts can
    # capture cleanly.
    print(f"Token id:    {row.id}", file=sys.stderr)
    print(f"Name:        {row.name}", file=sys.stderr)
    print(f"User:        {email} ({row.user_id})", file=sys.stderr)
    print(f"Scopes:      {', '.join(row.scopes)}", file=sys.stderr)
    print(
        "WARNING: this token will not be shown again. Store it now.",
        file=sys.stderr,
    )
    print(raw)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="reflections.mcp.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    mint = sub.add_parser("mint", help="Mint a new MCP token")
    mint.add_argument("--email", required=True)
    mint.add_argument("--name", required=True)
    mint.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        help=(
            "Repeatable. Known: mcp:read, mcp:write, mcp:read_private. "
            "Default: mcp:read,mcp:write (no private access)."
        ),
    )
    args = p.parse_args()

    if args.cmd == "mint":
        return asyncio.run(_mint(args.email, args.name, args.scopes))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
