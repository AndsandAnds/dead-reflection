from __future__ import annotations

import pytest  # type: ignore[import-not-found]

from reflections.entities.schemas import ExtractedEntities, _is_garbage_name


@pytest.mark.parametrize(
    "name",
    [
        "i", "I", "me", "you", "You", "we", "us",
        "he", "she", "they", "them", "him", "her",
        "my", "your", "our", "their",
        "myself", "yourself", "themselves",
        "this", "that", "someone", "anybody",
        "user", "assistant", "person", "people",
        "",
        " ",
        "a",  # 1-char
        "  x  ",  # 1-char after strip
    ],
)
def test_garbage_names_are_rejected(name: str) -> None:
    assert _is_garbage_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Sarah",
        "New York",
        "Yirgacheffe",
        "coffee",
        "pour-over",
        "birthday party",
        "Café Bar",
        "AI",  # 2 chars, real acronym; we keep these
    ],
)
def test_real_names_pass(name: str) -> None:
    assert _is_garbage_name(name) is False


def test_as_entities_strips_pronouns_and_dedupes() -> None:
    ee = ExtractedEntities(
        people=["Sarah", "you", "I", "Sarah", "sarah", "Me"],
        places=["Verve", "  ", "Verve"],
        events=["birthday"],
        topics=["coffee", "Coffee", "a"],
    )
    out = ee.as_entities()
    by_kind = {k: [e.name for e in out if e.kind == k] for k in {"person", "place", "event", "topic"}}
    # Pronouns filtered out, dedupe is case-insensitive on (kind, name)
    assert by_kind["person"] == ["Sarah"]
    assert by_kind["place"] == ["Verve"]
    assert by_kind["event"] == ["birthday"]
    # "Coffee" dedupes against "coffee"; "a" rejected as too short
    assert by_kind["topic"] == ["coffee"]


def test_as_entities_preserves_per_kind_dedupe() -> None:
    """A name appearing as both place and topic should pass through both."""
    ee = ExtractedEntities(
        places=["Brooklyn"],
        topics=["Brooklyn"],
    )
    out = ee.as_entities()
    assert {(e.kind, e.name) for e in out} == {("place", "Brooklyn"), ("topic", "Brooklyn")}


def test_as_entities_emits_orgs() -> None:
    """Bands / companies / teams come through with kind='org'."""
    ee = ExtractedEntities(
        people=["John Barr"],
        orgs=["The Hogs", "the hogs", "Anthropic"],
        topics=["music"],
    )
    out = ee.as_entities()
    by_kind = {
        k: [e.name for e in out if e.kind == k]
        for k in {"person", "org", "topic"}
    }
    assert by_kind["person"] == ["John Barr"]
    # Case-insensitive dedupe inside 'org' kicks in
    assert by_kind["org"] == ["The Hogs", "Anthropic"]
    assert by_kind["topic"] == ["music"]


def test_org_and_person_with_same_name_are_distinct() -> None:
    """Edge case: a person's surname matching an org name should not collide
    across kinds (per-kind dedupe only)."""
    ee = ExtractedEntities(
        people=["Anthropic"],   # contrived but should pass
        orgs=["Anthropic"],
    )
    out = ee.as_entities()
    assert {(e.kind, e.name) for e in out} == {
        ("person", "Anthropic"),
        ("org", "Anthropic"),
    }
