"""
Extraction policy matching.

A policy is a rule like:
  "for this volume, files matching `Photos/2024/*.jpg` with mime
  `image/jpeg` → extract (public)"
  "for this volume, files matching `Finances/*.pdf` → extract_private"
  "for this volume, files matching `Drafts/**` → ignore"

Rules are evaluated in `position` order; **first match wins**. Anything
that doesn't match any rule defaults to `ignore` — opt-in only, so
nothing on a 10TB drive accidentally gets extracted.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Literal

PolicyAction = Literal["extract", "extract_private", "ignore"]


@dataclass(frozen=True)
class Policy:
    glob_pattern: str | None
    mime_prefix: str | None
    kind: str | None
    action: PolicyAction


@dataclass(frozen=True)
class MatchResult:
    action: PolicyAction
    matched: Policy | None


def match(
    policies: list[Policy],
    *,
    relative_path: str,
    mime: str | None,
    kind: str,
) -> MatchResult:
    """Return the first policy that matches, or a default `ignore`."""
    for p in policies:
        if p.glob_pattern is not None:
            if not fnmatch.fnmatch(relative_path, p.glob_pattern):
                continue
        if p.mime_prefix is not None:
            if not (mime or "").lower().startswith(p.mime_prefix.lower()):
                continue
        if p.kind is not None and p.kind != kind:
            continue
        return MatchResult(action=p.action, matched=p)
    return MatchResult(action="ignore", matched=None)
