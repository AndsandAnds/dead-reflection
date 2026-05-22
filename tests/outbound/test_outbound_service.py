"""
Unit tests for OutboundService — the admin gate, the SSRF guard, the audit
write, and the DuckDuckGo Lite HTML parser.

We mock httpx so no real network call is made. The SSRF guard's DNS lookup
is also stubbed so tests don't depend on resolver behavior.
"""

from __future__ import annotations

import datetime as dt
import socket
from dataclasses import dataclass, field
from uuid import UUID

import httpx  # type: ignore[import-not-found]
import pytest  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid
from reflections.outbound import service as outbound_service
from reflections.outbound.exceptions import (
    OutboundForbiddenException,
    OutboundServiceException,
)
from reflections.outbound.service import (
    OutboundService,
    UserCtx,
    _parse_ddg_lite_html,
)


# --- fakes --------------------------------------------------------------------


@dataclass
class FakeAuditRepo:
    rows: list[dict] = field(default_factory=list)

    async def insert(
        self,
        _session,
        *,
        user_id: UUID,
        method: str,
        url: str,
        purpose: str | None,
        status_code: int | None,
        outcome: str,
        error: str | None,
        duration_ms: int | None,
    ):
        row = {
            "id": uuid7_uuid(),
            "user_id": user_id,
            "method": method,
            "url": url,
            "purpose": purpose,
            "status_code": status_code,
            "outcome": outcome,
            "error": error,
            "duration_ms": duration_ms,
            "ts": dt.datetime.now(dt.UTC),
        }
        self.rows.append(row)

        # Mimic the AuditRow attribute access pattern used by service.
        class R:
            pass

        r = R()
        for k, v in row.items():
            setattr(r, k, v)
        return r


class FakeSession:
    async def commit(self):
        return None

    async def rollback(self):
        return None


async def _allow_all_hosts(_host: str) -> str | None:
    """Stub _resolve_and_check_host for tests that aren't exercising SSRF."""
    return None


# --- admin gate ---------------------------------------------------------------


@pytest.mark.anyio
async def test_non_admin_is_denied_and_audited() -> None:
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=False)

    with pytest.raises(OutboundForbiddenException):
        await svc.request(
            FakeSession(),  # type: ignore[arg-type]
            user=user,
            method="GET",
            url="https://example.com",
            purpose="test",
        )

    assert len(repo.rows) == 1
    assert repo.rows[0]["outcome"] == "denied"
    assert repo.rows[0]["error"] == "user_not_admin"
    assert repo.rows[0]["status_code"] is None
    assert repo.rows[0]["user_id"] == user.id


@pytest.mark.anyio
async def test_admin_call_is_audited_with_status(monkeypatch) -> None:
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=True)

    # Mock the underlying httpx.AsyncClient so the test doesn't touch network.
    captured: dict = {}

    class _Resp:
        status_code = 200
        text = "ok"
        is_success = True

    class _Client:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs.get("headers")
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        outbound_service, "_resolve_and_check_host", _allow_all_hosts
    )

    resp = await svc.request(
        FakeSession(),  # type: ignore[arg-type]
        user=user,
        method="GET",
        url="https://example.com",
        purpose="probe",
    )
    assert resp.status_code == 200
    assert captured["method"] == "GET"
    assert captured["url"] == "https://example.com"
    # Default User-Agent is always present.
    assert "User-Agent" in captured["headers"]

    assert len(repo.rows) == 1
    row = repo.rows[0]
    assert row["outcome"] == "ok"
    assert row["status_code"] == 200
    assert row["purpose"] == "probe"
    assert row["duration_ms"] is not None


@pytest.mark.anyio
async def test_network_error_is_audited_as_error(monkeypatch) -> None:
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=True)

    class _Client:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def request(self, *_a, **_kw):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        outbound_service, "_resolve_and_check_host", _allow_all_hosts
    )

    with pytest.raises(OutboundServiceException):
        await svc.request(
            FakeSession(),  # type: ignore[arg-type]
            user=user,
            method="GET",
            url="https://nowhere.example",
        )

    assert len(repo.rows) == 1
    assert repo.rows[0]["outcome"] == "error"
    assert "ConnectError" in repo.rows[0]["error"]


# --- search end-to-end --------------------------------------------------------


@pytest.mark.anyio
async def test_internet_search_returns_parsed_hits(monkeypatch) -> None:
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=True)

    # Mirrors the real DDG Lite HTML: single quotes, href before class,
    # snippets contain <b>bolded</b> query terms.
    sample_html = """
    <a rel="nofollow" href="https://en.wikipedia.org/wiki/Talk_Talk" class='result-link'>Talk Talk - Wikipedia</a>
    <td class='result-snippet'><b>Talk</b> <b>Talk</b> were an English post-rock band formed in 1981.</td>
    <a rel="nofollow" href="https://talktalkofficial.com/" class='result-link'>Official Talk Talk site</a>
    <td class='result-snippet'>News, tour dates, and discography.</td>
    """

    class _Resp:
        status_code = 200
        text = sample_html
        is_success = True

    class _Client:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def request(self, *_a, **_kw):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        outbound_service, "_resolve_and_check_host", _allow_all_hosts
    )

    result = await svc.internet_search(
        FakeSession(),  # type: ignore[arg-type]
        user=user,
        query="talk talk band",
        top_k=5,
    )
    assert result.query == "talk talk band"
    assert len(result.hits) == 2
    assert result.hits[0].title == "Talk Talk - Wikipedia"
    # DDG redirect was unwrapped to the real URL.
    assert result.hits[0].url == "https://en.wikipedia.org/wiki/Talk_Talk"
    assert "1981" in result.hits[0].snippet
    assert result.hits[1].url == "https://talktalkofficial.com/"
    assert repo.rows[0]["purpose"] == "internet_search"


# --- parser direct unit tests -------------------------------------------------


def test_parser_strips_html_tags_in_titles_and_snippets() -> None:
    html = (
        '<a href="https://x.test" class="result-link">An <b>example</b> page</a>'
        '<td class="result-snippet">Short <i>preview</i> text</td>'
    )
    hits = _parse_ddg_lite_html(html)
    assert len(hits) == 1
    assert hits[0].title == "An example page"
    assert hits[0].snippet == "Short preview text"


def test_parser_handles_both_quote_styles_and_attr_orders() -> None:
    """DDG Lite uses single quotes and href-first ordering; ensure we cope."""
    html_single = (
        "<a href='https://a.test' class='result-link'>A</a>"
        "<td class='result-snippet'>aa</td>"
    )
    html_double_class_first = (
        '<a class="result-link" href="https://b.test">B</a>'
        '<td class="result-snippet">bb</td>'
    )
    a = _parse_ddg_lite_html(html_single)
    b = _parse_ddg_lite_html(html_double_class_first)
    assert (a[0].title, a[0].url) == ("A", "https://a.test")
    assert (b[0].title, b[0].url) == ("B", "https://b.test")


def test_parser_handles_no_results() -> None:
    assert _parse_ddg_lite_html("<html>nothing here</html>") == []


# --- SSRF guard ---------------------------------------------------------------


class _NetworkUsed(AssertionError):
    """Raised if a blocked target reaches the httpx layer (test failure)."""


@pytest.fixture()
def _explode_on_network(monkeypatch):
    """Replace httpx.AsyncClient with one that fails the test if instantiated."""

    class _Boom:
        def __init__(self, *_a, **_kw):
            raise _NetworkUsed("SSRF guard did not block before httpx was reached")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9999/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://192.168.1.1/admin",
    ],
)
async def test_ip_literal_targets_are_blocked_before_network(
    url, _explode_on_network
) -> None:
    """Loopback, link-local metadata, IPv6 loopback, RFC1918 → denied + audited."""
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=True)

    with pytest.raises(OutboundForbiddenException):
        await svc.request(
            FakeSession(),  # type: ignore[arg-type]
            user=user,
            method="GET",
            url=url,
        )

    assert len(repo.rows) == 1
    row = repo.rows[0]
    assert row["outcome"] == "denied"
    assert row["error"].startswith("blocked_internal_address:")
    assert row["url"] == url


@pytest.mark.anyio
async def test_internal_hostname_is_blocked_via_dns_resolution(
    monkeypatch, _explode_on_network
) -> None:
    """A docker-internal hostname like `db` that resolves to RFC1918 → denied."""
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=True)

    async def _fake_getaddrinfo(self, host, port, **_kwargs):
        assert host == "db"
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("172.18.0.2", 0),
            )
        ]

    monkeypatch.setattr(
        "asyncio.events.AbstractEventLoop.getaddrinfo", _fake_getaddrinfo
    )

    with pytest.raises(OutboundForbiddenException):
        await svc.request(
            FakeSession(),  # type: ignore[arg-type]
            user=user,
            method="GET",
            url="http://db:5432/",
        )

    assert len(repo.rows) == 1
    row = repo.rows[0]
    assert row["outcome"] == "denied"
    assert "172.18.0.2" in row["error"]


@pytest.mark.anyio
async def test_public_hostname_passes_through(monkeypatch) -> None:
    """A normal public hostname (DDG Lite-style) is allowed through to httpx."""
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=True)

    async def _fake_getaddrinfo(self, host, port, **_kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("40.89.244.232", 0),  # arbitrary public IP
            )
        ]

    monkeypatch.setattr(
        "asyncio.events.AbstractEventLoop.getaddrinfo", _fake_getaddrinfo
    )

    class _Resp:
        status_code = 200
        text = ""
        is_success = True

    class _Client:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def request(self, *_a, **_kw):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    resp = await svc.request(
        FakeSession(),  # type: ignore[arg-type]
        user=user,
        method="POST",
        url="https://lite.duckduckgo.com/lite/",
        purpose="internet_search",
    )
    assert resp.status_code == 200
    assert repo.rows[0]["outcome"] == "ok"


@pytest.mark.anyio
async def test_dns_failure_is_audited_as_error(monkeypatch) -> None:
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=True)

    async def _fake_getaddrinfo(self, host, port, **_kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(
        "asyncio.events.AbstractEventLoop.getaddrinfo", _fake_getaddrinfo
    )

    with pytest.raises(OutboundServiceException):
        await svc.request(
            FakeSession(),  # type: ignore[arg-type]
            user=user,
            method="GET",
            url="https://does-not-resolve.invalid/",
        )

    assert len(repo.rows) == 1
    assert repo.rows[0]["outcome"] == "error"
    assert "dns_resolution_failed" in repo.rows[0]["error"]


@pytest.mark.anyio
async def test_url_without_host_is_rejected(_explode_on_network) -> None:
    repo = FakeAuditRepo()
    svc = OutboundService(repo=repo)  # type: ignore[arg-type]
    user = UserCtx(id=uuid7_uuid(), is_admin=True)

    with pytest.raises(OutboundForbiddenException):
        await svc.request(
            FakeSession(),  # type: ignore[arg-type]
            user=user,
            method="GET",
            url="file:///etc/passwd",
        )

    assert repo.rows[0]["error"] == "invalid_url_no_host"
