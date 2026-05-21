"""Policy matching truth table + scope-gated recall via the repo layer."""

from __future__ import annotations

import pytest  # type: ignore[import-not-found]

from reflections.artifacts.policies import Policy, match


def _rules():
    return [
        # 1) Finance PDFs: extract, but private.
        Policy(
            glob_pattern="Finances/**",
            mime_prefix="application/pdf",
            kind=None,
            action="extract_private",
        ),
        # 2) Any photo under Photos/2024/: extract public.
        Policy(
            glob_pattern="Photos/2024/*",
            mime_prefix="image/",
            kind="image",
            action="extract",
        ),
        # 3) Anything else under Drafts/: ignore.
        Policy(
            glob_pattern="Drafts/**",
            mime_prefix=None,
            kind=None,
            action="ignore",
        ),
        # 4) Catch-all PDFs: public extract.
        Policy(
            glob_pattern=None,
            mime_prefix="application/pdf",
            kind="pdf",
            action="extract",
        ),
    ]


def test_first_match_wins_for_finance_pdf() -> None:
    r = match(
        _rules(),
        relative_path="Finances/2024/tax-return.pdf",
        mime="application/pdf",
        kind="pdf",
    )
    assert r.action == "extract_private"


def test_photo_rule_with_kind_constraint() -> None:
    r = match(
        _rules(),
        relative_path="Photos/2024/IMG_001.jpg",
        mime="image/jpeg",
        kind="image",
    )
    assert r.action == "extract"


def test_drafts_ignored_regardless_of_kind() -> None:
    r = match(
        _rules(),
        relative_path="Drafts/notes/2026-05.md",
        mime="text/markdown",
        kind="other",
    )
    assert r.action == "ignore"


def test_falls_through_to_catch_all_pdf() -> None:
    r = match(
        _rules(),
        relative_path="Docs/contract.pdf",
        mime="application/pdf",
        kind="pdf",
    )
    assert r.action == "extract"


def test_unmatched_defaults_to_ignore() -> None:
    r = match(
        _rules(),
        relative_path="Random/file.txt",
        mime="text/plain",
        kind="other",
    )
    assert r.action == "ignore"
    assert r.matched is None


@pytest.mark.parametrize(
    "mime_prefix,actual_mime,expected_match",
    [
        ("image/", "image/jpeg", True),
        ("image/", "Image/JPEG", True),  # case-insensitive
        ("image/", "video/mp4", False),
        ("audio/", None, False),
    ],
)
def test_mime_prefix_matching(mime_prefix, actual_mime, expected_match):
    p = Policy(
        glob_pattern=None,
        mime_prefix=mime_prefix,
        kind=None,
        action="extract",
    )
    r = match([p], relative_path="x", mime=actual_mime, kind="image")
    assert (r.action == "extract") is expected_match
