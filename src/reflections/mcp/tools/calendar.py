"""MCP tools that wrap the calendar service (Apple Calendar via host bridge)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from pydantic import Field

from reflections.calendar.exceptions import (
    CalendarNotAuthorizedException,
    CalendarNotConfiguredException,
)
from reflections.calendar.schemas import (
    CreateEventRequest,
    UpdateEventRequest,
)
from reflections.calendar.service import CalendarService
from reflections.mcp.auth import current_user_id  # noqa: F401  (gates auth)

_calendar_service: CalendarService | None = None


def _service() -> CalendarService:
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = CalendarService.default()
    return _calendar_service


def _check_auth_or_explain() -> None:
    """No-op now; auth happens via the token verifier. The function exists so
    tool docstrings can mention 'authenticated user' uniformly."""
    current_user_id()


def register(mcp) -> None:  # type: ignore[no-untyped-def]
    @mcp.tool
    async def list_calendars() -> dict:
        """
        List the user's Apple Calendars (name, id, color, source type).

        Requires the host calendar bridge to be running and the macOS user to
        have granted Calendar access. If the bridge isn't configured or
        permission hasn't been granted, the tool returns a structured error
        with a hint about how to fix it.
        """
        _check_auth_or_explain()
        try:
            cals = await _service().list_calendars()
            return {"items": [c.model_dump(mode="json") for c in cals]}
        except CalendarNotConfiguredException as exc:
            return {"error": "calendar_bridge_not_configured", "hint": exc.details}
        except CalendarNotAuthorizedException as exc:
            return {"error": "calendar_not_authorized", "hint": exc.details}

    @mcp.tool
    async def list_calendar_events(
        start: Annotated[dt.datetime, Field(description="ISO 8601 inclusive")],
        end: Annotated[dt.datetime, Field(description="ISO 8601 exclusive")],
        calendar_id: str | None = None,
    ) -> dict:
        """
        List events in the given time range. Both `start` and `end` are
        required ISO 8601 timestamps; pass a timezone offset (e.g. "Z" or
        "-05:00") for unambiguous results.

        If `calendar_id` is omitted, all readable calendars are searched.
        """
        _check_auth_or_explain()
        try:
            events = await _service().list_events(
                start=start, end=end, calendar_id=calendar_id
            )
            return {"items": [e.model_dump(mode="json") for e in events]}
        except CalendarNotConfiguredException as exc:
            return {"error": "calendar_bridge_not_configured", "hint": exc.details}
        except CalendarNotAuthorizedException as exc:
            return {"error": "calendar_not_authorized", "hint": exc.details}

    @mcp.tool
    async def create_calendar_event(
        title: Annotated[str, Field(min_length=1, max_length=500)],
        start: dt.datetime,
        end: dt.datetime,
        calendar_id: str | None = None,
        all_day: bool = False,
        location: str | None = None,
        notes: str | None = None,
        url: str | None = None,
    ) -> dict:
        """
        Create a new event in the user's Apple Calendar.

        - `calendar_id` defaults to the system's default calendar for new
          events when omitted.
        - `start`/`end` are ISO 8601 timestamps. Pass a timezone offset for
          unambiguous results.
        - For all-day events, set `all_day=true` and use date-only timestamps
          aligned to midnight in the target timezone.
        """
        _check_auth_or_explain()
        req = CreateEventRequest(
            title=title,
            start=start,
            end=end,
            calendar_id=calendar_id,
            all_day=all_day,
            location=location,
            notes=notes,
            url=url,
        )
        try:
            ev = await _service().create_event(req)
            return ev.model_dump(mode="json")
        except CalendarNotConfiguredException as exc:
            return {"error": "calendar_bridge_not_configured", "hint": exc.details}
        except CalendarNotAuthorizedException as exc:
            return {"error": "calendar_not_authorized", "hint": exc.details}

    @mcp.tool
    async def update_calendar_event(
        event_id: str,
        title: str | None = None,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        calendar_id: str | None = None,
        all_day: bool | None = None,
        location: str | None = None,
        notes: str | None = None,
        url: str | None = None,
    ) -> dict:
        """Update fields on an existing event. Only supplied fields change."""
        _check_auth_or_explain()
        req = UpdateEventRequest(
            title=title,
            start=start,
            end=end,
            calendar_id=calendar_id,
            all_day=all_day,
            location=location,
            notes=notes,
            url=url,
        )
        try:
            ev = await _service().update_event(event_id, req)
            return ev.model_dump(mode="json")
        except CalendarNotConfiguredException as exc:
            return {"error": "calendar_bridge_not_configured", "hint": exc.details}
        except CalendarNotAuthorizedException as exc:
            return {"error": "calendar_not_authorized", "hint": exc.details}

    @mcp.tool
    async def delete_calendar_event(event_id: str) -> dict:
        """Delete an event by id. Returns {deleted: true} on success."""
        _check_auth_or_explain()
        try:
            await _service().delete_event(event_id)
            return {"deleted": True}
        except CalendarNotConfiguredException as exc:
            return {"error": "calendar_bridge_not_configured", "hint": exc.details}
        except CalendarNotAuthorizedException as exc:
            return {"error": "calendar_not_authorized", "hint": exc.details}
