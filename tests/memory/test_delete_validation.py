import pytest  # type: ignore[import-not-found]
from uuid6 import uuid7  # type: ignore[import-not-found]

from reflections.memory.service import MemoryService


def test_delete_requires_ids() -> None:
    svc = MemoryService.create()
    with pytest.raises(Exception) as exc:
        # We don't need a real session to validate inputs; it fails before DB use.
        import asyncio

        asyncio.run(svc.delete(session=None, user_id=uuid7(), ids=[]))  # type: ignore[arg-type]
    assert "No ids" in str(exc.value)
