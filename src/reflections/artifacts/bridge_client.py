"""
Thin httpx client for the catalog bridge.

Kept separate from `service.py` so it can be mocked cleanly in tests and
swapped for an in-process implementation later if we ever bundle the
catalog walker inside the api container.
"""

from __future__ import annotations

from typing import Any

import httpx  # type: ignore[import-not-found]

from reflections.artifacts.exceptions import (
    ArtifactsNotConfiguredException,
    ArtifactsServiceException,
    VolumeOfflineException,
)
from reflections.core.settings import settings


def _base() -> str:
    if not settings.CATALOG_BRIDGE_URL:
        raise ArtifactsNotConfiguredException(
            "catalog_bridge_not_configured",
            "Set CATALOG_BRIDGE_URL to enable the artifact catalog.",
        )
    return settings.CATALOG_BRIDGE_URL.rstrip("/")


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    if settings.CATALOG_BRIDGE_SECRET:
        h["X-Catalog-Bridge-Secret"] = settings.CATALOG_BRIDGE_SECRET
    return h


def _client(timeout_s: float | None = None) -> httpx.AsyncClient:
    t = timeout_s if timeout_s is not None else float(
        settings.CATALOG_BRIDGE_TIMEOUT_S
    )
    return httpx.AsyncClient(timeout=httpx.Timeout(t))


def _raise(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
    except Exception:
        body = {"detail": resp.text[:300]}
    detail = body.get("detail") if isinstance(body, dict) else body
    if (
        resp.status_code in (404, 409)
        and isinstance(detail, dict)
        and detail.get("error") in {"path_not_a_directory", "mount_path_not_a_directory"}
    ):
        raise VolumeOfflineException(
            detail["error"],
            "The volume's mount path isn't reachable from the catalog bridge.",
        )
    raise ArtifactsServiceException(
        f"bridge_error_{resp.status_code}",
        str(detail) if detail is not None else "catalog bridge error",
    )


class CatalogBridgeClient:
    async def health(self) -> dict[str, Any]:
        try:
            base = _base()
        except ArtifactsNotConfiguredException:
            return {"configured": False, "reachable": False}
        try:
            async with _client(timeout_s=3.0) as c:
                r = await c.get(f"{base}/health", headers=_headers())
                r.raise_for_status()
                return {
                    "configured": True,
                    "reachable": True,
                    **r.json(),
                }
        except Exception as exc:
            return {
                "configured": True,
                "reachable": False,
                "detail": str(exc)[:200],
            }

    async def probe(
        self, *, mount_path: str, label: str | None = None
    ) -> dict[str, Any]:
        base = _base()
        async with _client() as c:
            r = await c.post(
                f"{base}/probe",
                headers=_headers(),
                json={"path": mount_path, "label": label},
            )
            _raise(r)
            return r.json()

    async def walk(
        self,
        *,
        mount_path: str,
        subpath: str = "",
        cursor: str | None = None,
        max_entries: int = 5000,
    ) -> dict[str, Any]:
        base = _base()
        params: dict[str, Any] = {
            "mount_path": mount_path,
            "subpath": subpath,
            "max_entries": max_entries,
        }
        if cursor:
            params["cursor"] = cursor
        # Walks of huge dirs can take a while; use a longer timeout.
        async with _client(timeout_s=60.0) as c:
            r = await c.get(
                f"{base}/walk", headers=_headers(), params=params
            )
            _raise(r)
            return r.json()

    async def fingerprint(
        self, *, mount_path: str, relative_path: str
    ) -> dict[str, Any]:
        base = _base()
        async with _client(timeout_s=300.0) as c:
            r = await c.get(
                f"{base}/fingerprint",
                headers=_headers(),
                params={
                    "mount_path": mount_path,
                    "relative_path": relative_path,
                },
            )
            _raise(r)
            return r.json()
