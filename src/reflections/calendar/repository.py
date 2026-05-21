"""
HTTP client to the host-side calendar_bridge.

The repository does the HTTP call and surfaces structured errors. All domain
logic lives in service.py.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx  # type: ignore[import-not-found]

from reflections.calendar.exceptions import (
    CalendarNotAuthorizedException,
    CalendarNotConfiguredException,
    CalendarNotFoundException,
    CalendarServiceException,
    CalendarUnprocessableException,
)
from reflections.core.settings import settings


def _base_url() -> str:
    if not settings.CALENDAR_BRIDGE_URL:
        raise CalendarNotConfiguredException(
            "calendar_bridge_not_configured",
            "Set CALENDAR_BRIDGE_URL to enable Apple Calendar integration.",
        )
    return settings.CALENDAR_BRIDGE_URL.rstrip("/")


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    if settings.CALENDAR_BRIDGE_SECRET:
        h["X-Calendar-Bridge-Secret"] = settings.CALENDAR_BRIDGE_SECRET
    return h


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
    except Exception:
        body = {"detail": resp.text[:300]}
    detail = body.get("detail") if isinstance(body, dict) else body
    # FastAPI nests our structured detail under "detail".
    if (
        isinstance(detail, dict)
        and detail.get("error") in {"calendar_not_authorized", "calendar_write_not_authorized"}
    ):
        raise CalendarNotAuthorizedException(
            detail["error"],
            detail.get("hint") or "Run POST /authorize on the calendar bridge.",
        )
    if resp.status_code == 404:
        raise CalendarNotFoundException(
            "not_found", str(detail) if detail is not None else "not found"
        )
    if 400 <= resp.status_code < 500:
        raise CalendarUnprocessableException(
            f"bridge_{resp.status_code}", str(detail) if detail is not None else "bad request"
        )
    raise CalendarServiceException(
        f"bridge_error_{resp.status_code}",
        str(detail) if detail is not None else "calendar bridge error",
    )


class CalendarBridgeRepository:
    async def health(self) -> dict[str, Any]:
        try:
            base = _base_url()
        except CalendarNotConfiguredException:
            return {"configured": False, "reachable": False}
        timeout = httpx.Timeout(min(3.0, float(settings.CALENDAR_BRIDGE_TIMEOUT_S)))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{base}/health", headers=_headers())
                r.raise_for_status()
                data = r.json()
            return {
                "configured": True,
                "reachable": True,
                "auth_status": data.get("auth_status"),
                "auth_status_code": data.get("auth_status_code"),
                "base_url": base,
            }
        except Exception as exc:
            return {
                "configured": True,
                "reachable": False,
                "base_url": base,
                "detail": str(exc)[:200],
            }

    async def authorize(self) -> dict[str, Any]:
        base = _base_url()
        timeout = httpx.Timeout(35.0)  # may wait for the user to click "Allow"
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{base}/authorize", headers=_headers())
            _raise_for_status(r)
            return r.json()

    async def list_calendars(self) -> list[dict[str, Any]]:
        base = _base_url()
        timeout = httpx.Timeout(float(settings.CALENDAR_BRIDGE_TIMEOUT_S))
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{base}/calendars", headers=_headers())
            _raise_for_status(r)
            return r.json()

    async def list_events(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        calendar_id: str | None = None,
    ) -> list[dict[str, Any]]:
        base = _base_url()
        params: dict[str, Any] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        if calendar_id:
            params["calendar_id"] = calendar_id
        timeout = httpx.Timeout(float(settings.CALENDAR_BRIDGE_TIMEOUT_S))
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                f"{base}/events", headers=_headers(), params=params
            )
            _raise_for_status(r)
            return r.json()

    async def create_event(self, body: dict[str, Any]) -> dict[str, Any]:
        base = _base_url()
        timeout = httpx.Timeout(float(settings.CALENDAR_BRIDGE_TIMEOUT_S))
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{base}/events", headers=_headers(), json=body
            )
            _raise_for_status(r)
            return r.json()

    async def update_event(
        self, event_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        base = _base_url()
        timeout = httpx.Timeout(float(settings.CALENDAR_BRIDGE_TIMEOUT_S))
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.patch(
                f"{base}/events/{event_id}", headers=_headers(), json=body
            )
            _raise_for_status(r)
            return r.json()

    async def delete_event(self, event_id: str) -> None:
        base = _base_url()
        timeout = httpx.Timeout(float(settings.CALENDAR_BRIDGE_TIMEOUT_S))
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.delete(
                f"{base}/events/{event_id}", headers=_headers()
            )
            _raise_for_status(r)
