from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from reflections.calendar.exceptions import CalendarUnprocessableException
from reflections.calendar.repository import CalendarBridgeRepository
from reflections.calendar.schemas import (
    BridgeHealth,
    Calendar,
    CalendarEvent,
    CreateEventRequest,
    UpdateEventRequest,
)


def _to_calendar(d: dict) -> Calendar:
    return Calendar(
        id=d["id"],
        title=d["title"],
        color=d.get("color"),
        type=d.get("type"),
        allows_modification=bool(d.get("allows_modification", True)),
    )


def _to_event(d: dict) -> CalendarEvent:
    return CalendarEvent(
        id=d["id"],
        calendar_id=d["calendar_id"],
        title=d.get("title") or "",
        start=d["start"],
        end=d["end"],
        all_day=bool(d.get("all_day", False)),
        location=d.get("location"),
        notes=d.get("notes"),
        url=d.get("url"),
        attendees=list(d.get("attendees") or []),
    )


@dataclass
class CalendarService:
    repo: CalendarBridgeRepository

    @classmethod
    def default(cls) -> "CalendarService":
        return cls(repo=CalendarBridgeRepository())

    async def health(self) -> BridgeHealth:
        h = await self.repo.health()
        return BridgeHealth(
            configured=bool(h.get("configured")),
            reachable=bool(h.get("reachable")),
            auth_status=h.get("auth_status"),
            auth_status_code=h.get("auth_status_code"),
            base_url=h.get("base_url"),
            detail=h.get("detail"),
        )

    async def authorize(self) -> BridgeHealth:
        result = await self.repo.authorize()
        return BridgeHealth(
            configured=True,
            reachable=True,
            auth_status=result.get("auth_status"),
            auth_status_code=result.get("auth_status_code"),
        )

    async def list_calendars(self) -> list[Calendar]:
        rows = await self.repo.list_calendars()
        return [_to_calendar(d) for d in rows]

    async def list_events(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        calendar_id: str | None = None,
    ) -> list[CalendarEvent]:
        if end <= start:
            raise CalendarUnprocessableException(
                "bad_range", "end must be after start"
            )
        rows = await self.repo.list_events(
            start=start, end=end, calendar_id=calendar_id
        )
        return [_to_event(d) for d in rows]

    async def create_event(self, req: CreateEventRequest) -> CalendarEvent:
        if req.end <= req.start:
            raise CalendarUnprocessableException(
                "bad_range", "end must be after start"
            )
        body = req.model_dump(mode="json", exclude_none=True)
        return _to_event(await self.repo.create_event(body))

    async def update_event(
        self, event_id: str, req: UpdateEventRequest
    ) -> CalendarEvent:
        if req.start is not None and req.end is not None and req.end <= req.start:
            raise CalendarUnprocessableException(
                "bad_range", "end must be after start"
            )
        body = req.model_dump(mode="json", exclude_none=True)
        return _to_event(await self.repo.update_event(event_id, body))

    async def delete_event(self, event_id: str) -> None:
        await self.repo.delete_event(event_id)
