from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.auth.depends import current_user_required
from reflections.calendar.exceptions import (
    CalendarNotAuthorizedException,
    CalendarNotConfiguredException,
    CalendarNotFoundException,
    CalendarServiceException,
    CalendarUnprocessableException,
)
from reflections.calendar.schemas import (
    BridgeHealth,
    Calendar,
    CalendarEvent,
    CreateEventRequest,
    UpdateEventRequest,
)
from reflections.calendar.service import CalendarService

router = APIRouter(prefix="/calendar", tags=["calendar"])


@lru_cache
def get_calendar_service() -> CalendarService:
    return CalendarService.default()


def _map_exc(exc: Exception) -> HTTPException:
    if isinstance(exc, CalendarNotConfiguredException):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.details or exc.message,
        )
    if isinstance(exc, CalendarNotAuthorizedException):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.details or exc.message,
        )
    if isinstance(exc, CalendarNotFoundException):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.details or exc.message,
        )
    if isinstance(exc, CalendarUnprocessableException):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.details or exc.message,
        )
    if isinstance(exc, CalendarServiceException):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.details or exc.message,
        )
    raise exc  # pragma: no cover


@router.get("/health", response_model=BridgeHealth)
async def calendar_health(
    svc: Annotated[CalendarService, Depends(get_calendar_service)],
    _user=Depends(current_user_required),
) -> BridgeHealth:
    return await svc.health()


@router.post("/authorize", response_model=BridgeHealth)
async def calendar_authorize(
    svc: Annotated[CalendarService, Depends(get_calendar_service)],
    _user=Depends(current_user_required),
) -> BridgeHealth:
    try:
        return await svc.authorize()
    except Exception as exc:
        raise _map_exc(exc)


@router.get("/calendars", response_model=list[Calendar])
async def list_calendars(
    svc: Annotated[CalendarService, Depends(get_calendar_service)],
    _user=Depends(current_user_required),
) -> list[Calendar]:
    try:
        return await svc.list_calendars()
    except Exception as exc:
        raise _map_exc(exc)


@router.get("/events", response_model=list[CalendarEvent])
async def list_events(
    svc: Annotated[CalendarService, Depends(get_calendar_service)],
    _user=Depends(current_user_required),
    start: dt.datetime = Query(...),
    end: dt.datetime = Query(...),
    calendar_id: str | None = Query(default=None),
) -> list[CalendarEvent]:
    try:
        return await svc.list_events(
            start=start, end=end, calendar_id=calendar_id
        )
    except Exception as exc:
        raise _map_exc(exc)


@router.post("/events", response_model=CalendarEvent, status_code=status.HTTP_201_CREATED)
async def create_event(
    req: CreateEventRequest,
    svc: Annotated[CalendarService, Depends(get_calendar_service)],
    _user=Depends(current_user_required),
) -> CalendarEvent:
    try:
        return await svc.create_event(req)
    except Exception as exc:
        raise _map_exc(exc)


@router.patch("/events/{event_id}", response_model=CalendarEvent)
async def update_event(
    event_id: str,
    req: UpdateEventRequest,
    svc: Annotated[CalendarService, Depends(get_calendar_service)],
    _user=Depends(current_user_required),
) -> CalendarEvent:
    try:
        return await svc.update_event(event_id, req)
    except Exception as exc:
        raise _map_exc(exc)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    svc: Annotated[CalendarService, Depends(get_calendar_service)],
    _user=Depends(current_user_required),
) -> None:
    try:
        await svc.delete_event(event_id)
    except Exception as exc:
        raise _map_exc(exc)
