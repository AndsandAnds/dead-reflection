from __future__ import annotations

from pydantic import BaseModel


class ExportStats(BaseModel):
    daily_notes: int
    entity_notes: int
    memories: int
    entities: int


class ImportStats(BaseModel):
    memories_updated: int
    memories_reembedded: int
    entities_updated: int
    skipped: int
    errors: list[str]
