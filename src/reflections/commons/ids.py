from __future__ import annotations

from uuid import UUID

from uuid6 import uuid7  # type: ignore[import-not-found]


def uuid7_uuid() -> UUID:
    """Generate a UUIDv7 (project-wide standard)."""
    return uuid7()


def uuid7_str() -> str:
    """Generate a UUIDv7 string (for display/logging)."""
    return str(uuid7_uuid())
