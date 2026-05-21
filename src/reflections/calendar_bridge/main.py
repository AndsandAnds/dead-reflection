"""
Apple Calendar bridge — runs on the macOS host (NOT in Docker).

EventKit is a native macOS framework that requires user consent via the
system Privacy & Security dialog. It can only run on the Mac itself, so we
follow the same host-bridge pattern as the STT and TTS bridges.

The FastAPI app inside the api Docker container talks to this bridge over
HTTP via host.docker.internal:9004.

Startup:
  make calendar-bridge       # foreground
  make calendar-bridge-bg    # background, PID file in ./run

First-time consent:
  POST /authorize             # triggers the macOS permission prompt

Optional shared-secret header `X-Calendar-Bridge-Secret` if
CALENDAR_BRIDGE_SECRET is set, so other Mac apps can't poke this port.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

# pyobjc — only imported on macOS hosts. The Docker image NEVER imports this
# module; the api talks to the bridge over HTTP.
import EventKit  # type: ignore[import-not-found]
import Foundation  # type: ignore[import-not-found]


# --- Models -------------------------------------------------------------------


class CalendarSummary(BaseModel):
    id: str
    title: str
    color: str | None = None
    type: str | None = None
    allows_modification: bool = True


class EventModel(BaseModel):
    id: str
    calendar_id: str
    title: str
    start: dt.datetime
    end: dt.datetime
    all_day: bool = False
    location: str | None = None
    notes: str | None = None
    url: str | None = None
    attendees: list[str] = Field(default_factory=list)


class CreateEventRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    start: dt.datetime
    end: dt.datetime
    calendar_id: str | None = None
    all_day: bool = False
    location: str | None = None
    notes: str | None = None
    url: str | None = None


class UpdateEventRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    start: dt.datetime | None = None
    end: dt.datetime | None = None
    calendar_id: str | None = None
    all_day: bool | None = None
    location: str | None = None
    notes: str | None = None
    url: str | None = None


class HealthResponse(BaseModel):
    status: str
    auth_status: str
    auth_status_code: int


class AuthorizeResponse(BaseModel):
    granted: bool
    auth_status: str
    auth_status_code: int


# --- App + EventKit state -----------------------------------------------------


app = FastAPI(title="Reflections Calendar Bridge", version="0.1.0")
_store_lock = threading.Lock()
_store: Any = None  # EKEventStore singleton


def _get_store() -> Any:
    """Lazy singleton EKEventStore — created once per process."""
    global _store
    with _store_lock:
        if _store is None:
            _store = EventKit.EKEventStore.alloc().init()
        return _store


# EKAuthorizationStatus enum (matches macOS values)
_AUTH_STATUS_NAMES = {
    0: "notDetermined",
    1: "restricted",
    2: "denied",
    3: "authorized",       # legacy, pre-macOS 14
    4: "writeOnly",        # macOS 14+
    5: "fullAccess",       # macOS 14+
}


def _auth_status() -> tuple[int, str]:
    code = int(
        EventKit.EKEventStore.authorizationStatusForEntityType_(
            EventKit.EKEntityTypeEvent
        )
    )
    return code, _AUTH_STATUS_NAMES.get(code, f"unknown_{code}")


def _is_authorized_for_read(code: int) -> bool:
    # Anything that grants at least read access.
    return code in (3, 4, 5)


def _is_authorized_for_write(code: int) -> bool:
    return code in (3, 5)


def _require_auth(*, write: bool = False) -> None:
    code, name = _auth_status()
    if write and not _is_authorized_for_write(code):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "calendar_write_not_authorized",
                "auth_status": name,
                "hint": "Run POST /authorize, then grant full access in System Settings → Privacy & Security → Calendars.",
            },
        )
    if not write and not _is_authorized_for_read(code):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "calendar_not_authorized",
                "auth_status": name,
                "hint": "Run POST /authorize, then approve the macOS prompt.",
            },
        )


# --- Secret header guard ------------------------------------------------------


def _check_secret(supplied: str | None) -> None:
    expected = os.environ.get("CALENDAR_BRIDGE_SECRET")
    if not expected:
        return
    if supplied != expected:
        raise HTTPException(
            status_code=401, detail="invalid_calendar_bridge_secret"
        )


# --- Date helpers -------------------------------------------------------------


def _nsdate(ts: dt.datetime) -> Any:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.UTC)
    return Foundation.NSDate.dateWithTimeIntervalSince1970_(ts.timestamp())


def _from_nsdate(nsd: Any) -> dt.datetime:
    return dt.datetime.fromtimestamp(nsd.timeIntervalSince1970(), tz=dt.UTC)


def _calendar_summary(cal: Any) -> CalendarSummary:
    # Best-effort color: NSColor → hex if available, else None.
    color = None
    nsc = cal.color() if cal.respondsToSelector_("color") else None
    if nsc is not None:
        try:
            srgb = nsc.colorUsingColorSpace_(
                Foundation.NSColorSpace.sRGBColorSpace()
            )
            if srgb is not None:
                r, g, b = (
                    int(round(srgb.redComponent() * 255)),
                    int(round(srgb.greenComponent() * 255)),
                    int(round(srgb.blueComponent() * 255)),
                )
                color = f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            color = None
    type_code = int(cal.type())
    type_names = {
        0: "local",
        1: "calDAV",
        2: "exchange",
        3: "subscription",
        4: "birthday",
    }
    return CalendarSummary(
        id=str(cal.calendarIdentifier()),
        title=str(cal.title()),
        color=color,
        type=type_names.get(type_code, f"unknown_{type_code}"),
        allows_modification=bool(cal.allowsContentModifications()),
    )


def _event_model(ev: Any) -> EventModel:
    attendees: list[str] = []
    ek_atts = ev.attendees() if ev.respondsToSelector_("attendees") else None
    if ek_atts:
        for a in ek_atts:
            name = a.name() if a.respondsToSelector_("name") else None
            if name:
                attendees.append(str(name))
    url_obj = ev.URL() if ev.respondsToSelector_("URL") else None
    return EventModel(
        id=str(ev.eventIdentifier()),
        calendar_id=str(ev.calendar().calendarIdentifier()),
        title=str(ev.title() or ""),
        start=_from_nsdate(ev.startDate()),
        end=_from_nsdate(ev.endDate()),
        all_day=bool(ev.isAllDay()),
        location=str(ev.location()) if ev.location() else None,
        notes=str(ev.notes()) if ev.notes() else None,
        url=str(url_obj.absoluteString()) if url_obj is not None else None,
        attendees=attendees,
    )


def _find_calendar(store: Any, calendar_id: str) -> Any:
    cals = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
    for cal in cals:
        if str(cal.calendarIdentifier()) == calendar_id:
            return cal
    return None


# --- Routes -------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health(
    x_calendar_bridge_secret: Annotated[str | None, Header()] = None,
) -> HealthResponse:
    _check_secret(x_calendar_bridge_secret)
    code, name = _auth_status()
    return HealthResponse(status="ok", auth_status=name, auth_status_code=code)


@app.post("/authorize", response_model=AuthorizeResponse)
def authorize(
    x_calendar_bridge_secret: Annotated[str | None, Header()] = None,
) -> AuthorizeResponse:
    """
    Trigger the macOS Calendar permission prompt (or return current status if
    already granted/denied). Blocks until the system completes the callback.

    On macOS 14+ we ask for full access (read + write). On older macOS we fall
    back to the legacy requestAccessToEntityType API.
    """
    _check_secret(x_calendar_bridge_secret)
    store = _get_store()

    done = threading.Event()
    granted_box = {"granted": False, "error": None}

    def _handler(granted: bool, err: Any) -> None:
        granted_box["granted"] = bool(granted)
        if err is not None:
            granted_box["error"] = str(err)
        done.set()

    if store.respondsToSelector_(
        "requestFullAccessToEventsWithCompletion:"
    ):
        store.requestFullAccessToEventsWithCompletion_(_handler)
    else:
        # Legacy API (pre-macOS 14). Still works on newer OS as well.
        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeEvent, _handler
        )

    # Cap the wait so we don't block forever if macOS misbehaves.
    done.wait(timeout=30)
    code, name = _auth_status()
    return AuthorizeResponse(
        granted=bool(granted_box["granted"]) and _is_authorized_for_read(code),
        auth_status=name,
        auth_status_code=code,
    )


@app.get("/calendars", response_model=list[CalendarSummary])
def list_calendars(
    x_calendar_bridge_secret: Annotated[str | None, Header()] = None,
) -> list[CalendarSummary]:
    _check_secret(x_calendar_bridge_secret)
    _require_auth()
    store = _get_store()
    cals = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
    return [_calendar_summary(c) for c in cals]


@app.get("/events", response_model=list[EventModel])
def list_events(
    start: dt.datetime = Query(..., description="ISO 8601, inclusive"),
    end: dt.datetime = Query(..., description="ISO 8601, exclusive"),
    calendar_id: str | None = Query(default=None),
    x_calendar_bridge_secret: Annotated[str | None, Header()] = None,
) -> list[EventModel]:
    _check_secret(x_calendar_bridge_secret)
    _require_auth()
    store = _get_store()

    if calendar_id is not None:
        cal = _find_calendar(store, calendar_id)
        if cal is None:
            raise HTTPException(status_code=404, detail="calendar_not_found")
        cals = [cal]
    else:
        cals = list(store.calendarsForEntityType_(EventKit.EKEntityTypeEvent))

    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        _nsdate(start), _nsdate(end), cals
    )
    events = store.eventsMatchingPredicate_(predicate) or []
    # EventKit returns in calendar order; sort by start for stable output.
    out = [_event_model(e) for e in events]
    out.sort(key=lambda e: e.start)
    return out


@app.post("/events", response_model=EventModel)
def create_event(
    req: CreateEventRequest,
    x_calendar_bridge_secret: Annotated[str | None, Header()] = None,
) -> EventModel:
    _check_secret(x_calendar_bridge_secret)
    _require_auth(write=True)
    store = _get_store()

    if req.calendar_id:
        cal = _find_calendar(store, req.calendar_id)
        if cal is None:
            raise HTTPException(status_code=404, detail="calendar_not_found")
    else:
        cal = store.defaultCalendarForNewEvents()
        if cal is None:
            raise HTTPException(
                status_code=400, detail="no_default_calendar_for_new_events"
            )

    ev = EventKit.EKEvent.eventWithEventStore_(store)
    ev.setTitle_(req.title)
    ev.setStartDate_(_nsdate(req.start))
    ev.setEndDate_(_nsdate(req.end))
    ev.setAllDay_(bool(req.all_day))
    if req.location is not None:
        ev.setLocation_(req.location)
    if req.notes is not None:
        ev.setNotes_(req.notes)
    if req.url is not None:
        ev.setURL_(Foundation.NSURL.URLWithString_(req.url))
    ev.setCalendar_(cal)

    ok, err = store.saveEvent_span_error_(
        ev, EventKit.EKSpanThisEvent, None
    )
    if not ok:
        raise HTTPException(
            status_code=500,
            detail=f"save_failed: {err}",
        )
    return _event_model(ev)


@app.patch("/events/{event_id}", response_model=EventModel)
def update_event(
    event_id: str,
    req: UpdateEventRequest,
    x_calendar_bridge_secret: Annotated[str | None, Header()] = None,
) -> EventModel:
    _check_secret(x_calendar_bridge_secret)
    _require_auth(write=True)
    store = _get_store()

    ev = store.eventWithIdentifier_(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="event_not_found")

    if req.title is not None:
        ev.setTitle_(req.title)
    if req.start is not None:
        ev.setStartDate_(_nsdate(req.start))
    if req.end is not None:
        ev.setEndDate_(_nsdate(req.end))
    if req.all_day is not None:
        ev.setAllDay_(bool(req.all_day))
    if req.location is not None:
        ev.setLocation_(req.location)
    if req.notes is not None:
        ev.setNotes_(req.notes)
    if req.url is not None:
        ev.setURL_(Foundation.NSURL.URLWithString_(req.url))
    if req.calendar_id is not None:
        cal = _find_calendar(store, req.calendar_id)
        if cal is None:
            raise HTTPException(status_code=404, detail="calendar_not_found")
        ev.setCalendar_(cal)

    ok, err = store.saveEvent_span_error_(
        ev, EventKit.EKSpanThisEvent, None
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"save_failed: {err}")
    return _event_model(ev)


@app.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: str,
    x_calendar_bridge_secret: Annotated[str | None, Header()] = None,
) -> None:
    _check_secret(x_calendar_bridge_secret)
    _require_auth(write=True)
    store = _get_store()

    ev = store.eventWithIdentifier_(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="event_not_found")

    ok, err = store.removeEvent_span_error_(
        ev, EventKit.EKSpanThisEvent, None
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"delete_failed: {err}")
