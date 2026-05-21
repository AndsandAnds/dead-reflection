from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Calendar(BaseModel):
    id: str
    title: str
    color: str | None = None
    type: str | None = None
    allows_modification: bool = True


class CalendarEvent(BaseModel):
    id: str
    calendar_id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str | None = None
    notes: str | None = None
    url: str | None = None
    attendees: list[str] = Field(default_factory=list)


class CreateEventRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    start: datetime
    end: datetime
    calendar_id: str | None = None
    all_day: bool = False
    location: str | None = None
    notes: str | None = None
    url: str | None = None


class UpdateEventRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    start: datetime | None = None
    end: datetime | None = None
    calendar_id: str | None = None
    all_day: bool | None = None
    location: str | None = None
    notes: str | None = None
    url: str | None = None


class BridgeHealth(BaseModel):
    configured: bool
    reachable: bool
    auth_status: str | None = None
    auth_status_code: int | None = None
    base_url: str | None = None
    detail: str | None = None
