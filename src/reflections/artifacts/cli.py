"""
Command-line tools for the artifact catalog.

The `crawl` subcommand is the convenience workflow for "I have a folder
full of files I want indexed":

  make crawl-folder email=you@example.com path=/Volumes/Photos-10TB \
       [label='Photos Archive'] [subpath=2024] [max_pages=500]

What it does:
  1. Resolves the user by email
  2. Registers the path as a volume (idempotent — reuses an existing
     row when the marker file is already present)
  3. Walks the volume in pages of 5000 entries until done (or until
     max_pages is hit, in case the user wants to bound an initial test
     against a giant drive)
  4. Prints summary stats: how many files added / updated / unchanged,
     wall-clock time

It does NOT run extractors. Extraction is a separate step driven by
policies (`set_extraction_policy` + `apply_extraction_policies` MCP
tools, or REST). This keeps the crawl cheap and idempotent — running
the same `make crawl-folder` again is safe.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from reflections.artifacts.service import ArtifactsService
from reflections.auth.repository import AuthRepository
from reflections.core.db import database_manager


async def _crawl(
    email: str,
    path: str,
    label: str | None,
    subpath: str,
    max_pages: int,
) -> int:
    # NOTE: `path` is a HOST-side path. The catalog bridge walks the
    # host filesystem (the api container doesn't mount it), so we just
    # normalize it here — the bridge is the source of truth for whether
    # the directory exists and will surface a clear error if it doesn't.
    p = Path(path).expanduser()
    abs_path = str(p if p.is_absolute() else p.resolve())

    await database_manager.initialize()
    async with database_manager.session() as session:
        user = await AuthRepository().get_user_by_email(session, email=email)
        if user is None:
            print(f"error: no user with email {email!r}", file=sys.stderr)
            return 2

        svc = ArtifactsService.default()
        print(
            f"\n  Registering volume at {abs_path}"
            f"{' (label: ' + label + ')' if label else ''}",
            file=sys.stderr,
        )
        volume = await svc.register_volume(
            session,
            user_id=user.id,
            mount_path=abs_path,
            label=label,
        )
        print(
            f"  Volume: {volume.label} (id={volume.id})\n"
            f"  fingerprint={volume.fingerprint or '-'}, "
            f"volume_uuid={volume.volume_uuid or '-'}",
            file=sys.stderr,
        )

        print(
            f"\n  Walking {abs_path}{'/' + subpath if subpath else ''}...",
            file=sys.stderr,
        )
        start = time.monotonic()
        result = await svc.catalog_volume(
            session,
            user_id=user.id,
            volume_id=volume.id,
            subpath=subpath,
            max_pages=max_pages,
        )
        elapsed = time.monotonic() - start

    print("", file=sys.stderr)
    print(f"  Files seen:        {result['files_seen']}", file=sys.stderr)
    print(f"  Newly added:       {result['files_added']}", file=sys.stderr)
    print(f"  Updated (changed): {result['files_updated']}", file=sys.stderr)
    print(f"  Unchanged:         {result['files_unchanged']}", file=sys.stderr)
    print(f"  Pages fetched:     {result['pages_fetched']}", file=sys.stderr)
    print(f"  Elapsed:           {elapsed:.2f}s", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "  Next: run extraction via the MCP tools "
        "`set_extraction_policy` + `apply_extraction_policies`,",
        file=sys.stderr,
    )
    print("  or the REST endpoints under /artifacts/.", file=sys.stderr)

    # Stdout: just the volume id so scripts can chain.
    print(volume.id)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="reflections.artifacts.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    crawl = sub.add_parser(
        "crawl",
        help="Register a folder as a volume and walk it (stat-only)",
    )
    crawl.add_argument("--email", required=True, help="User to register the volume under")
    crawl.add_argument("--path", required=True, help="Absolute path on the host")
    crawl.add_argument("--label", default=None)
    crawl.add_argument(
        "--subpath",
        default="",
        help="Optional subpath under the mount root (relative)",
    )
    crawl.add_argument(
        "--max-pages",
        type=int,
        default=200,
        help="Cap on walk pages (5000 entries each). Default 200 (~1M files).",
    )
    args = p.parse_args()

    if args.cmd == "crawl":
        return asyncio.run(
            _crawl(
                email=args.email,
                path=args.path,
                label=args.label,
                subpath=args.subpath,
                max_pages=args.max_pages,
            )
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
