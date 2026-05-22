from reflections.memory.schemas import Turn
from reflections.memory.service import (
    chunk_turns_by_window,
    extract_memory_cards_heuristic,
)


def test_chunk_turns_by_window_emits_plain_text_no_role_prefix() -> None:
    """The chunk formatter MUST NOT add role prefixes — they leak into
    storage. The ingest pipeline filters to user-only turns upstream;
    this function just joins their content."""
    turns = [
        Turn(role="user", content="one"),
        Turn(role="user", content="three"),
        Turn(role="user", content="five"),
    ]
    chunks = chunk_turns_by_window(turns, window=2)
    assert len(chunks) == 2
    assert chunks[0] == "one\nthree"
    assert chunks[1] == "five"
    # Guard against regression to the old role-prefixed format.
    for chunk in chunks:
        assert "user:" not in chunk
        assert "assistant:" not in chunk


def test_chunk_turns_by_window_skips_empty_groups() -> None:
    """If a group ends up empty after content filtering, no chunk
    should be emitted (no blank rows in memory_items)."""
    turns = [
        Turn(role="user", content="   "),
        Turn(role="user", content=""),
    ]
    assert chunk_turns_by_window(turns, window=2) == []


def test_extract_memory_cards_heuristic_is_conservative() -> None:
    turns = [
        Turn(role="user", content="I prefer low latency voice."),
        Turn(role="assistant", content="Got it."),
        Turn(role="user", content="We will run on Apple Silicon."),
    ]
    cards = extract_memory_cards_heuristic(turns)
    assert any("prefer" in c.lower() for c in cards)
    assert any("apple silicon" in c.lower() for c in cards)
