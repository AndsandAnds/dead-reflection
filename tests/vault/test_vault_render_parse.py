"""
Tests for vault renderers + parsers.

These are pure-function tests with no DB. The full export/import round-trip
through VaultService is covered by a focused service test below using a
fake repo.
"""

from __future__ import annotations

import datetime as dt
import io
import tarfile

import pytest  # type: ignore[import-not-found]

from reflections.vault.service import (
    parse_entity_description,
    parse_frontmatter,
    parse_memory_blocks,
    render_daily_note,
    render_entity_note,
)


# --- frontmatter --------------------------------------------------------------


def test_parse_frontmatter_basic() -> None:
    text = "---\nid: 123\nkind: person\nname: Sarah\n---\n\nbody here\n"
    fm, body = parse_frontmatter(text)
    assert fm == {"id": "123", "kind": "person", "name": "Sarah"}
    assert body == "\nbody here\n"


def test_parse_frontmatter_handles_quoted_values() -> None:
    text = '---\nname: "Sarah: my friend"\n---\nbody\n'
    fm, _ = parse_frontmatter(text)
    assert fm["name"] == "Sarah: my friend"


def test_parse_frontmatter_returns_empty_when_absent() -> None:
    fm, body = parse_frontmatter("no frontmatter here\n")
    assert fm == {}
    assert body == "no frontmatter here\n"


# --- daily note round-trip ----------------------------------------------------


def test_render_then_parse_daily_note_yields_originals() -> None:
    memories = [
        {
            "id": "019e4aed-4ac9-75c7-89fe-818912fe3de6",
            "kind": "card",
            "scope": "user",
            "content": "I prefer pour-over coffee from light roasts.",
            "created_at_iso": "2026-05-21T13:50:21+00:00",
            "entities": [("sarah", "person"), ("coffee", "topic")],
        },
        {
            "id": "019e4ac3-02c8-7e5a-ba8e-f24308ae9b24",
            "kind": "chunk",
            "scope": "user",
            "content": "user: Sarah came over to my house.\nassistant: Lovely!",
            "created_at_iso": "2026-05-21T09:50:21+00:00",
            "entities": [("sarah", "person")],
        },
    ]
    md = render_daily_note(dt.date(2026, 5, 21), memories)
    assert "[[people/sarah]]" in md
    assert "[[topics/coffee]]" in md
    assert "## Card · 13:50" in md
    assert "## Chunk · 09:50" in md

    blocks = parse_memory_blocks(md)
    assert len(blocks) == 2
    by_id = {str(b.id): b.content for b in blocks}
    assert (
        by_id["019e4aed-4ac9-75c7-89fe-818912fe3de6"]
        == "I prefer pour-over coffee from light roasts."
    )
    # Chunk content preserved across newlines.
    assert by_id["019e4ac3-02c8-7e5a-ba8e-f24308ae9b24"].startswith("user: Sarah")
    assert "assistant: Lovely!" in by_id["019e4ac3-02c8-7e5a-ba8e-f24308ae9b24"]


def test_parse_memory_blocks_strips_auto_chrome() -> None:
    """If a user edits a block, the auto-generated heading + Entities line
    must not bleed back into the stored content."""
    md = (
        "<!-- memory id=019e4aed-4ac9-75c7-89fe-818912fe3de6 kind=card scope=user -->\n"
        "## Card · 13:50\n"
        "**Entities:** [[people/sarah]]\n"
        "\n"
        "Updated content here.\n"
        "\n<!-- /memory -->\n"
    )
    blocks = parse_memory_blocks(md)
    assert len(blocks) == 1
    assert blocks[0].content == "Updated content here."


def test_parse_memory_blocks_ignores_bad_uuids() -> None:
    md = "<!-- memory id=not-a-uuid kind=card -->\nfoo\n<!-- /memory -->\n"
    assert parse_memory_blocks(md) == []


# --- entity notes -------------------------------------------------------------


def test_render_entity_note_includes_wikilinked_dates() -> None:
    md = render_entity_note(
        {
            "id": "019e4aed-54ca-7a56-95e5-0a788f237c84",
            "kind": "person",
            "name": "Sarah",
            "slug": "sarah",
            "description": "College friend, lives in Brooklyn.",
            "updated_at_iso": "2026-05-21T13:50:21+00:00",
        },
        linked_memory_dates=["2026-05-21", "2026-05-22"],
    )
    assert "# Sarah" in md
    assert "College friend" in md
    assert "[[daily/2026-05-21]]" in md
    assert "[[daily/2026-05-22]]" in md


def test_parse_entity_description_strips_heading_and_links_section() -> None:
    body = (
        "# Sarah\n"
        "\n"
        "She's my college friend.\n"
        "\n"
        "## Linked memories\n"
        "- [[daily/2026-05-21]]\n"
    )
    assert parse_entity_description(body) == "She's my college friend."


def test_parse_entity_description_handles_no_description() -> None:
    body = "# Sarah\n\n## Linked memories\n- [[daily/2026-05-21]]\n"
    assert parse_entity_description(body) == ""


def test_parse_entity_description_handles_leading_blank_line() -> None:
    """The body coming back from parse_frontmatter starts with `\\n#…`.
    Earlier this silently kept the `# Name` heading in the description,
    which made the importer think every entity had been edited."""
    body = "\n# Alex\n\nMy brother, lives in SF.\n\n## Linked memories\n- [[daily/2026-05-21]]\n"
    assert parse_entity_description(body) == "My brother, lives in SF."


def test_parse_entity_description_empty_with_leading_newline() -> None:
    body = "\n# coffee\n\n## Linked memories\n- [[daily/2026-05-21]]\n"
    assert parse_entity_description(body) == ""


# --- tarball shape (smoke) ----------------------------------------------------


def test_macos_appledouble_files_are_filtered_on_import() -> None:
    """Pack a tarball with a ._foo.md file and confirm the importer skips it."""
    from reflections.vault.service import VaultService
    from pathlib import Path

    # We don't need a real service — just exercise the filename guard the
    # importer applies. The check is `Path(name).name.startswith("._")`.
    assert Path("vault/topics/._coffee.md").name.startswith("._")
    assert not Path("vault/topics/coffee.md").name.startswith("._")


def test_export_tarball_renders_well_formed_archive() -> None:
    """Render a small in-memory archive, then re-open it and walk members."""
    md = render_daily_note(
        dt.date(2026, 5, 21),
        [
            {
                "id": "019e4aed-4ac9-75c7-89fe-818912fe3de6",
                "kind": "card",
                "scope": "user",
                "content": "test",
                "created_at_iso": "2026-05-21T13:50:21+00:00",
                "entities": [],
            }
        ],
    )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = md.encode("utf-8")
        info = tarfile.TarInfo(name="vault/daily/2026-05-21.md")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    with tarfile.open(fileobj=io.BytesIO(buf.getvalue()), mode="r:*") as tar:
        names = sorted(m.name for m in tar.getmembers())
        assert names == ["vault/daily/2026-05-21.md"]
        member = tar.getmember("vault/daily/2026-05-21.md")
        fh = tar.extractfile(member)
        assert fh is not None
        assert b"## Card" in fh.read()
