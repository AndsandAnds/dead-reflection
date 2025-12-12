from reflections.memory.schemas import Turn
from reflections.memory.service import (
    chunk_turns_by_window,
    extract_memory_cards_heuristic,
)


def test_chunk_turns_by_window_groups_turns() -> None:
    turns = [
        Turn(role="user", content="one"),
        Turn(role="assistant", content="two"),
        Turn(role="user", content="three"),
        Turn(role="assistant", content="four"),
        Turn(role="user", content="five"),
    ]
    chunks = chunk_turns_by_window(turns, window=2)
    assert len(chunks) == 3
    assert "user: one" in chunks[0]
    assert "assistant: two" in chunks[0]


def test_extract_memory_cards_heuristic_is_conservative() -> None:
    turns = [
        Turn(role="user", content="I prefer low latency voice."),
        Turn(role="assistant", content="Got it."),
        Turn(role="user", content="We will run on Apple Silicon."),
    ]
    cards = extract_memory_cards_heuristic(turns)
    assert any("prefer" in c.lower() for c in cards)
    assert any("apple silicon" in c.lower() for c in cards)
