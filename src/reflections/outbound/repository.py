from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid

metadata = sa.MetaData()


outbound_audit_log_table = sa.Table(
    "outbound_audit_log",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("user_id", sa.Uuid(), nullable=False),
    sa.Column("method", sa.Text(), nullable=False),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("purpose", sa.Text(), nullable=True),
    sa.Column("status_code", sa.Integer(), nullable=True),
    sa.Column("outcome", sa.Text(), nullable=False),
    sa.Column("error", sa.Text(), nullable=True),
    sa.Column("duration_ms", sa.Integer(), nullable=True),
    sa.Column(
        "ts",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
)


@dataclass(frozen=True)
class AuditRow:
    id: UUID
    user_id: UUID
    method: str
    url: str
    purpose: str | None
    status_code: int | None
    outcome: str
    error: str | None
    duration_ms: int | None
    ts: dt.datetime


def _row(r: Any) -> AuditRow:
    return AuditRow(
        id=r.id,
        user_id=r.user_id,
        method=r.method,
        url=r.url,
        purpose=r.purpose,
        status_code=r.status_code,
        outcome=r.outcome,
        error=r.error,
        duration_ms=r.duration_ms,
        ts=r.ts,
    )


@dataclass(frozen=True)
class OutboundAuditRepository:
    async def insert(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        method: str,
        url: str,
        purpose: str | None,
        status_code: int | None,
        outcome: str,
        error: str | None,
        duration_ms: int | None,
    ) -> AuditRow:
        stmt = (
            sa.insert(outbound_audit_log_table)
            .values(
                id=uuid7_uuid(),
                user_id=user_id,
                method=method,
                url=url,
                purpose=purpose,
                status_code=status_code,
                outcome=outcome,
                error=error,
                duration_ms=duration_ms,
            )
            .returning(
                outbound_audit_log_table.c.id,
                outbound_audit_log_table.c.user_id,
                outbound_audit_log_table.c.method,
                outbound_audit_log_table.c.url,
                outbound_audit_log_table.c.purpose,
                outbound_audit_log_table.c.status_code,
                outbound_audit_log_table.c.outcome,
                outbound_audit_log_table.c.error,
                outbound_audit_log_table.c.duration_ms,
                outbound_audit_log_table.c.ts,
            )
        )
        r = (await session.execute(stmt)).first()
        await session.flush()
        return _row(r)

    async def list_recent(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
        user_id: UUID | None = None,
        outcome: str | None = None,
    ) -> list[AuditRow]:
        conds: list[Any] = []
        if user_id is not None:
            conds.append(outbound_audit_log_table.c.user_id == user_id)
        if outcome is not None:
            conds.append(outbound_audit_log_table.c.outcome == outcome)
        stmt = sa.select(
            outbound_audit_log_table.c.id,
            outbound_audit_log_table.c.user_id,
            outbound_audit_log_table.c.method,
            outbound_audit_log_table.c.url,
            outbound_audit_log_table.c.purpose,
            outbound_audit_log_table.c.status_code,
            outbound_audit_log_table.c.outcome,
            outbound_audit_log_table.c.error,
            outbound_audit_log_table.c.duration_ms,
            outbound_audit_log_table.c.ts,
        )
        if conds:
            stmt = stmt.where(sa.and_(*conds))
        stmt = (
            stmt.order_by(outbound_audit_log_table.c.ts.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(stmt)).all()
        return [_row(r) for r in rows]
