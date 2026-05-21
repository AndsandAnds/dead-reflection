"""
Tests for the calendar module — without touching the macOS EventKit bridge.

We mock the repository so we can drive the service end-to-end with fake
bridge responses, and we exercise _raise_for_status directly to verify the
HTTP→exception mapping.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import httpx  # type: ignore[import-not-found]
import pytest  # type: ignore[import-not-found]

from reflections.calendar.exceptions import (
    CalendarNotAuthorizedException,
    CalendarNotFoundException,
    CalendarUnprocessableException,
)
from reflections.calendar.repository import _raise_for_status
from reflections.calendar.schemas import (
    CreateEventRequest,
    UpdateEventRequest,
)
from reflections.calendar.service import CalendarService


@dataclass
class FakeRepo:
    calendars: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    create_returns: dict | None = None
    update_returns: dict | None = None
    deleted: list[str] = field(default_factory=list)
    list_events_calls: list[tuple] = field(default_factory=list)

    async def list_calendars(self):
        return self.calendars

    async def list_events(self, *, start, end, calendar_id=None):
        self.list_events_calls.append((start, end, calendar_id))
        return self.events

    async def create_event(self, body):
        assert self.create_returns is not None
        return self.create_returns

    async def update_event(self, event_id, body):
        assert self.update_returns is not None
        return self.update_returns

    async def delete_event(self, event_id):
        self.deleted.append(event_id)

    async def health(self):
        return {"configured": True, "reachable": True}

    async def authorize(self):
        return {"auth_status": "fullAccess", "auth_status_code": 5}


@pytest.mark.anyio
async def test_list_calendars_normalizes_bridge_shape() -> None:
    repo = FakeRepo(
        calendars=[
            {
                "id": "abc",
                "title": "Work",
                "color": "#ff0000",
                "type": "calDAV",
                "allows_modification": True,
            },
            {
                "id": "def",
                "title": "Birthdays",
                "color": None,
                "type": "birthday",
                "allows_modification": False,
            },
        ]
    )
    svc = CalendarService(repo=repo)  # type: ignore[arg-type]
    cals = await svc.list_calendars()
    assert [c.id for c in cals] == ["abc", "def"]
    assert cals[0].color == "#ff0000"
    assert cals[1].allows_modification is False


@pytest.mark.anyio
async def test_list_events_rejects_inverted_range() -> None:
    svc = CalendarService(repo=FakeRepo())  # type: ignore[arg-type]
    t = dt.datetime(2026, 5, 21, 12, 0, tzinfo=dt.UTC)
    with pytest.raises(CalendarUnprocessableException):
        await svc.list_events(start=t, end=t)
    with pytest.raises(CalendarUnprocessableException):
        await svc.list_events(start=t, end=t - dt.timedelta(hours=1))


@pytest.mark.anyio
async def test_list_events_normalizes_results() -> None:
    repo = FakeRepo(
        events=[
            {
                "id": "ev1",
                "calendar_id": "cal1",
                "title": "Lunch with Sarah",
                "start": "2026-05-21T12:00:00+00:00",
                "end": "2026-05-21T13:00:00+00:00",
                "all_day": False,
                "location": "Verve",
                "notes": None,
                "url": None,
                "attendees": ["Sarah"],
            }
        ]
    )
    svc = CalendarService(repo=repo)  # type: ignore[arg-type]
    out = await svc.list_events(
        start=dt.datetime(2026, 5, 21, tzinfo=dt.UTC),
        end=dt.datetime(2026, 5, 22, tzinfo=dt.UTC),
    )
    assert len(out) == 1
    ev = out[0]
    assert ev.id == "ev1"
    assert ev.title == "Lunch with Sarah"
    assert ev.location == "Verve"
    assert ev.attendees == ["Sarah"]
    assert ev.all_day is False


@pytest.mark.anyio
async def test_create_event_rejects_inverted_range() -> None:
    svc = CalendarService(repo=FakeRepo())  # type: ignore[arg-type]
    t = dt.datetime(2026, 5, 21, 12, 0, tzinfo=dt.UTC)
    req = CreateEventRequest(title="Lunch", start=t, end=t)
    with pytest.raises(CalendarUnprocessableException):
        await svc.create_event(req)


@pytest.mark.anyio
async def test_create_event_passes_to_repo_and_normalizes() -> None:
    repo = FakeRepo(
        create_returns={
            "id": "newev",
            "calendar_id": "cal1",
            "title": "Lunch with Sarah",
            "start": "2026-05-21T12:00:00+00:00",
            "end": "2026-05-21T13:00:00+00:00",
            "all_day": False,
            "location": None,
            "notes": None,
            "url": None,
            "attendees": [],
        }
    )
    svc = CalendarService(repo=repo)  # type: ignore[arg-type]
    req = CreateEventRequest(
        title="Lunch with Sarah",
        start=dt.datetime(2026, 5, 21, 12, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 5, 21, 13, 0, tzinfo=dt.UTC),
    )
    out = await svc.create_event(req)
    assert out.id == "newev"
    assert out.title == "Lunch with Sarah"


@pytest.mark.anyio
async def test_update_event_rejects_partial_inverted_range() -> None:
    svc = CalendarService(repo=FakeRepo())  # type: ignore[arg-type]
    t = dt.datetime(2026, 5, 21, 12, 0, tzinfo=dt.UTC)
    req = UpdateEventRequest(start=t, end=t - dt.timedelta(minutes=1))
    with pytest.raises(CalendarUnprocessableException):
        await svc.update_event("ev1", req)


@pytest.mark.anyio
async def test_delete_event_calls_repo() -> None:
    repo = FakeRepo()
    svc = CalendarService(repo=repo)  # type: ignore[arg-type]
    await svc.delete_event("ev1")
    assert repo.deleted == ["ev1"]


# --- _raise_for_status mapping ------------------------------------------------


def _resp(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code, json=body, request=httpx.Request("GET", "http://t/")
    )


def test_raise_for_status_passes_2xx() -> None:
    _raise_for_status(_resp(200, {"ok": True}))  # no raise


def test_raise_for_status_maps_404() -> None:
    with pytest.raises(CalendarNotFoundException):
        _raise_for_status(_resp(404, {"detail": "event_not_found"}))


def test_raise_for_status_maps_auth_detail() -> None:
    body = {
        "detail": {
            "error": "calendar_not_authorized",
            "auth_status": "denied",
            "hint": "Run POST /authorize",
        }
    }
    with pytest.raises(CalendarNotAuthorizedException):
        _raise_for_status(_resp(403, body))


def test_raise_for_status_maps_write_auth_detail() -> None:
    body = {
        "detail": {
            "error": "calendar_write_not_authorized",
            "auth_status": "writeOnly",
            "hint": "Grant full access",
        }
    }
    with pytest.raises(CalendarNotAuthorizedException):
        _raise_for_status(_resp(403, body))


def test_raise_for_status_maps_4xx_to_unprocessable() -> None:
    with pytest.raises(CalendarUnprocessableException):
        _raise_for_status(_resp(422, {"detail": "bad input"}))
