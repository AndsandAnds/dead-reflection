"""
Regression: assistant utterances must not contribute proper nouns to
the entity graph. The extractor is fed only user-attributed text, so
hallucinations in the assistant's reply ("you mean Verve?") never
become real nodes.

Covers the `user_only_text` helper in memory/service.py.
"""

from __future__ import annotations

import pytest  # type: ignore[import-not-found]

from reflections.memory.service import user_only_text


def test_strips_assistant_lines_from_voice_chunk() -> None:
    chunk = "user: I went hiking this weekend\nassistant: Where did you go? Verve in Coney Island?"
    out = user_only_text(chunk)
    assert out == "I went hiking this weekend"
    # The assistant's invented "Verve" / "Coney Island" must not leak through.
    assert "Verve" not in out
    assert "Coney Island" not in out


def test_handles_multi_turn_user_lines() -> None:
    chunk = (
        "user: Saw The Hogs play last night\n"
        "assistant: Where was that?\n"
        "user: At Bowery Ballroom"
    )
    out = user_only_text(chunk)
    # Both user statements present, both assistant lines gone.
    assert "The Hogs" in out
    assert "Bowery Ballroom" in out
    assert "Where was that" not in out


def test_raw_card_text_passes_through_unchanged() -> None:
    """A card created via record_memory MCP tool has no role prefixes —
    treat the whole string as user content."""
    raw = "My favorite vinyl is Spirit of Eden by Talk Talk"
    assert user_only_text(raw) == raw


def test_multiline_raw_text_passes_through() -> None:
    raw = "Line one\nLine two has Marufuku ramen\nLine three"
    out = user_only_text(raw)
    # No `user:` prefix anywhere → entire blob is treated as user-attributed
    # and returned (after .strip()) unchanged so all 3 lines are extractable.
    assert "Marufuku" in out
    assert "Line one" in out
    assert "Line three" in out


def test_empty_input_returns_empty() -> None:
    assert user_only_text("") == ""
    assert user_only_text("   \n\n  ") == ""


def test_assistant_only_chunk_returns_empty() -> None:
    """Pathological case — chunk somehow contains only assistant text.
    Caller should skip extraction entirely rather than send empty text
    to the LLM."""
    chunk = "assistant: I think we discussed this before."
    assert user_only_text(chunk) == ""


def test_user_prefix_with_space_variant() -> None:
    """Some serializers emit `user :` with a space — handle gracefully."""
    chunk = "user : My grandfather's name was Henry"
    assert user_only_text(chunk) == "My grandfather's name was Henry"


def test_leading_whitespace_before_role_prefix() -> None:
    """Indented role prefix (rare but possible from copy/paste)."""
    chunk = "  user: I love coffee\n  assistant: What kind?"
    out = user_only_text(chunk)
    assert out == "I love coffee"


@pytest.mark.parametrize(
    "case",
    [
        # (input, must_contain, must_not_contain)
        (
            "user: Met Maya at Tartine\nassistant: Was Sarah there too?",
            ["Maya", "Tartine"],
            ["Sarah"],
        ),
        (
            "user: Just listened to Spirit of Eden\nassistant: That's the Mark Hollis project right?",
            ["Spirit of Eden"],
            ["Mark Hollis"],
        ),
    ],
)
def test_assistant_proper_nouns_dont_leak(
    case: tuple[str, list[str], list[str]],
) -> None:
    chunk, must_contain, must_not_contain = case
    out = user_only_text(chunk)
    for s in must_contain:
        assert s in out, f"expected user statement {s!r} in {out!r}"
    for s in must_not_contain:
        assert s not in out, (
            f"assistant proper noun {s!r} leaked into extractor input: {out!r}"
        )
