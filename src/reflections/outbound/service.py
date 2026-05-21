"""
Outbound HTTP service.

All outbound calls made on behalf of a user MUST go through this service so we
can (a) enforce the admin-only egress rule and (b) audit every attempt.

The service does both the network call and the audit write in one transaction
boundary; callers don't need to manage logging themselves.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.commons.logging import logger
from reflections.core.settings import settings
from reflections.outbound.exceptions import (
    OutboundForbiddenException,
    OutboundServiceException,
)
from reflections.outbound.repository import AuditRow, OutboundAuditRepository
from reflections.outbound.schemas import InternetSearchResult, SearchHit

DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
DEFAULT_USER_AGENT = "Reflections/1.0 (+local; PrivacyByDefault)"


@dataclass
class UserCtx:
    """Minimal user shape the wrapper needs. We avoid coupling to ORM models."""

    id: Any
    is_admin: bool


@dataclass
class OutboundService:
    repo: OutboundAuditRepository

    @classmethod
    def default(cls) -> "OutboundService":
        return cls(repo=OutboundAuditRepository())

    async def _audit(
        self,
        session: AsyncSession,
        *,
        user_id,
        method: str,
        url: str,
        purpose: str | None,
        status_code: int | None,
        outcome: str,
        error: str | None,
        duration_ms: int | None,
    ) -> AuditRow:
        # Best-effort: we never want a logging failure to swallow a real result
        # or block a denial response. Errors are logged then swallowed.
        try:
            row = await self.repo.insert(
                session,
                user_id=user_id,
                method=method,
                url=url,
                purpose=purpose,
                status_code=status_code,
                outcome=outcome,
                error=error,
                duration_ms=duration_ms,
            )
            await session.commit()
            return row
        except Exception as exc:
            await session.rollback()
            logger.warning("outbound_audit_write_failed url=%s err=%s", url, exc)
            # Re-raise only in dev; production should never crash on audit
            # write. For now: return a synthesized row.
            return AuditRow(
                id=user_id,  # placeholder; caller doesn't rely on this
                user_id=user_id,
                method=method,
                url=url,
                purpose=purpose,
                status_code=status_code,
                outcome=outcome,
                error=error,
                duration_ms=duration_ms,
                ts=None,  # type: ignore[arg-type]
            )

    async def request(
        self,
        session: AsyncSession,
        *,
        user: UserCtx,
        method: str,
        url: str,
        purpose: str | None = None,
        params: dict | None = None,
        json: Any | None = None,
        data: Any | None = None,
        headers: dict | None = None,
        timeout_s: float = 15.0,
    ) -> httpx.Response:
        """
        Make an outbound request as `user`. Raises OutboundForbiddenException
        for non-admin users (and audits the attempt). Always audits on success
        and on network failures.
        """
        if not user.is_admin:
            await self._audit(
                session,
                user_id=user.id,
                method=method.upper(),
                url=url,
                purpose=purpose,
                status_code=None,
                outcome="denied",
                error="user_not_admin",
                duration_ms=None,
            )
            raise OutboundForbiddenException(
                "internet_forbidden",
                "Outbound internet calls are restricted to admin users",
            )

        merged_headers = {"User-Agent": DEFAULT_USER_AGENT, **(headers or {})}
        proxy_url = getattr(settings, "EGRESS_PROXY_URL", None) or None

        client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(timeout_s)}
        if proxy_url:
            # When the optional egress proxy is configured, all outbound
            # traffic from this wrapper routes through it.
            client_kwargs["proxy"] = proxy_url

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=merged_headers,
                )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self._audit(
                session,
                user_id=user.id,
                method=method.upper(),
                url=url,
                purpose=purpose,
                status_code=None,
                outcome="error",
                error=type(exc).__name__ + ": " + str(exc)[:200],
                duration_ms=duration_ms,
            )
            raise OutboundServiceException(
                "outbound_call_failed", str(exc)
            ) from exc

        duration_ms = int((time.monotonic() - start) * 1000)
        await self._audit(
            session,
            user_id=user.id,
            method=method.upper(),
            url=url,
            purpose=purpose,
            status_code=resp.status_code,
            outcome="ok" if resp.is_success else "error",
            error=None if resp.is_success else f"http_{resp.status_code}",
            duration_ms=duration_ms,
        )
        return resp

    async def internet_search(
        self,
        session: AsyncSession,
        *,
        user: UserCtx,
        query: str,
        top_k: int = 5,
    ) -> InternetSearchResult:
        """
        Search the public web via DuckDuckGo Lite (no API key, HTML scrape).

        Admin only. Audits the call. Returns up to `top_k` parsed hits.
        """
        if not query.strip():
            return InternetSearchResult(query=query, hits=[])
        resp = await self.request(
            session,
            user=user,
            method="POST",
            url=DDG_LITE_URL,
            purpose="internet_search",
            data={"q": query, "kl": "us-en"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        hits = _parse_ddg_lite_html(resp.text)[:top_k]
        return InternetSearchResult(query=query, hits=hits)


# --- DuckDuckGo Lite HTML parser ---------------------------------------------


# The DDG Lite HTML is intentionally simple (designed for text browsers).
# Each result is an <a ... class='result-link'>title</a> followed shortly by a
# <td class='result-snippet'>snippet</td>. Quote style is single OR double and
# attribute order isn't guaranteed (href and class can appear in either
# order), so we use a two-pass approach: match the whole anchor with the
# class attribute anywhere, then extract href from it.
_RESULT_LINK_RE = re.compile(
    r"""<a\b([^>]*?\bclass\s*=\s*['"]result-link['"][^>]*)>(.*?)</a>""",
    re.DOTALL | re.IGNORECASE,
)
_HREF_RE = re.compile(r"""href\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)
_SNIPPET_RE = re.compile(
    r"""<td\b[^>]*?\bclass\s*=\s*['"]result-snippet['"][^>]*>(.*?)</td>""",
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return unescape(_TAG_RE.sub("", s)).strip()


def _unwrap_ddg_redirect(href: str) -> str:
    """DDG wraps results as /l/?uddg=<encoded-url>. Unwrap when present."""
    try:
        parsed = urlparse(href)
        if parsed.path.endswith("/l/") or parsed.path == "/l/":
            qs = parse_qs(parsed.query)
            uddg = qs.get("uddg", [None])[0]
            if uddg:
                return unquote(uddg)
    except Exception:
        pass
    return href


def _parse_ddg_lite_html(html: str) -> list[SearchHit]:
    links = _RESULT_LINK_RE.findall(html)
    snippets = _SNIPPET_RE.findall(html)
    out: list[SearchHit] = []
    for idx, (attrs, title_html) in enumerate(links):
        href_m = _HREF_RE.search(attrs)
        if not href_m:
            continue
        href = href_m.group(1)
        snippet = _strip_tags(snippets[idx]) if idx < len(snippets) else ""
        out.append(
            SearchHit(
                title=_strip_tags(title_html),
                url=_unwrap_ddg_redirect(href),
                snippet=snippet,
            )
        )
    return out
