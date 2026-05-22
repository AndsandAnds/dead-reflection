from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import UUID

import httpx  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.core.settings import settings
from reflections.entities.exceptions import (
    EntitiesNotFoundException,
    EntitiesServiceException,
    EntitiesUnprocessableException,
)
from reflections.entities.repository import (
    EntitiesRepository,
    EntityRow,
    slugify,
)
from reflections.entities.schemas import (
    EntityKind,
    ExtractedEntities,
    ExtractedEntity,
)


class _LLMExtractor(Protocol):
    async def extract(self, text: str) -> ExtractedEntities: ...


class OllamaEntityExtractor:
    """
    Calls Ollama in JSON-mode to extract entities from a chunk of conversation.

    The shape mirrors `ExtractedEntities`. We keep this simple and tolerant:
    if the LLM returns garbage we just fall back to an empty result.
    """

    SYSTEM_PROMPT = (
        "Extract named entities from the conversation chunk.\n"
        "Reply ONLY with JSON, no prose, no code fences, matching this schema:\n"
        '{"people": [string], "places": [string], '
        '"events": [string], "topics": [string], "orgs": [string]}\n'
        "\n"
        "Categories:\n"
        "- people:  individual humans, by name (\"Sarah\", \"Dr. Levin\").\n"
        "- places:  physical locations (\"Verve\", \"Coney Island\", \"San Francisco\").\n"
        "- events:  things that happen at a point in time (\"birthday\", "
        "\"Siren Festival\", \"kickoff\").\n"
        "- topics:  short noun phrases describing what the text is ABOUT "
        "(\"coffee\", \"climate-tech\", \"vinyl\").\n"
        "- orgs:    named collectives — bands, companies, teams, clubs, "
        "schools, charities, podcasts, government bodies. A band's NAME "
        "belongs here, not in 'people'. Examples: \"The Hogs\", \"Anthropic\", "
        "\"Warriors\", \"Boy Scouts\".\n"
        "\n"
        "Rules — STRICT:\n"
        "1. NEVER include pronouns or generic referents as entities. "
        "Forbidden as 'people': I, me, my, you, your, we, us, our, he, him, "
        "she, her, they, them, user, assistant, someone, anyone, person.\n"
        "2. The narrator/speaker (the 'I' in the text) is NEVER an entity. "
        "Only extract OTHER people, by their actual name.\n"
        "3. Use the shortest canonical name. 'Sarah', not 'my friend Sarah'. "
        "'The Hogs', not 'a band named The Hogs'.\n"
        "4. Prefer specific over generic. 'Yirgacheffe' is a better place "
        "than 'Ethiopia' if both are mentioned. 'Verve' is a better place "
        "than 'coffee shop'. 'The Hogs' is a better org than 'band'.\n"
        "5. A band name is an ORG, not a person. \"The Hogs played with "
        "The Micks\" → orgs: [\"The Hogs\", \"The Micks\"]. Individual band "
        "members go in 'people' only when their personal name appears.\n"
        "6. Topics are about abstract subjects (\"music\", \"coffee\"), not "
        "named things. If you have a proper noun, prefer org/place/event "
        "over topic.\n"
        "7. If nothing of a kind appears, return an empty list for that kind.\n"
        "8. Keep each list under 10 items.\n"
        "\n"
        "Examples:\n"
        '  Input: "I prefer pour-over coffee from Ethiopia, Yirgacheffe beans."\n'
        '  Output: {"people": [], "places": ["Yirgacheffe", "Ethiopia"], '
        '"events": [], "topics": ["coffee", "pour-over"], "orgs": []}\n'
        "\n"
        '  Input: "Sarah and I went to Verve in Santa Cruz for her birthday."\n'
        '  Output: {"people": ["Sarah"], "places": ["Verve", "Santa Cruz"], '
        '"events": ["birthday"], "topics": [], "orgs": []}\n'
        "\n"
        '  Input: "John Barr is in a band named The Hogs with Justin Wise '
        'and Corey Hamm."\n'
        '  Output: {"people": ["John Barr", "Justin Wise", "Corey Hamm"], '
        '"places": [], "events": [], "topics": ["music"], '
        '"orgs": ["The Hogs"]}\n'
        "\n"
        '  Input: "The Hogs played Siren Festival in Coney Island with '
        'The Micks, Abhors, and Swamps."\n'
        '  Output: {"people": [], "places": ["Coney Island"], '
        '"events": ["Siren Festival"], "topics": [], '
        '"orgs": ["The Hogs", "The Micks", "Abhors", "Swamps"]}\n'
    )

    async def extract(self, text: str) -> ExtractedEntities:
        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "options": {"temperature": 0.0},
        }
        timeout_s = float(settings.OLLAMA_TIMEOUT_S)
        timeout = httpx.Timeout(timeout_s, connect=min(2.0, timeout_s))
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
            resp = await client.post("/api/chat", json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        content = (data.get("message") or {}).get("content") or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return ExtractedEntities()
        try:
            return ExtractedEntities.model_validate(parsed)
        except Exception:
            return ExtractedEntities()


@dataclass
class EntitiesService:
    repo: EntitiesRepository
    extractor_factory: Callable[[], _LLMExtractor]

    @classmethod
    def create(cls) -> "EntitiesService":
        return cls(
            repo=EntitiesRepository(),
            extractor_factory=lambda: OllamaEntityExtractor(),
        )

    # ---- CRUD ----

    async def list_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        kind: EntityKind | None,
        limit: int,
        offset: int,
    ) -> list[EntityRow]:
        return await self.repo.list_entities(
            session, user_id=user_id, kind=kind, limit=limit, offset=offset
        )

    async def get(
        self, session: AsyncSession, *, user_id: UUID, entity_id: UUID
    ) -> EntityRow:
        row = await self.repo.get_by_id(
            session, user_id=user_id, entity_id=entity_id
        )
        if row is None:
            raise EntitiesNotFoundException(
                "entity_not_found", "No entity with that id for this user"
            )
        return row

    async def add(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        kind: EntityKind,
        name: str,
        description: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> EntityRow:
        name_stripped = name.strip()
        if not name_stripped:
            raise EntitiesUnprocessableException(
                "empty_name", "Entity name must be non-empty"
            )
        slug = slugify(name_stripped)
        # Idempotent: return the existing entity if one already exists with the
        # same (user, kind, slug). Refreshes description/attributes when supplied.
        existing = await self.repo.get_by_slug(
            session, user_id=user_id, kind=kind, slug=slug
        )
        if existing is not None:
            if description is not None or attributes is not None:
                await self.repo.update(
                    session,
                    entity_id=existing.id,
                    user_id=user_id,
                    description=description,
                    attributes=attributes,
                )
                refreshed = await self.repo.get_by_id(
                    session, user_id=user_id, entity_id=existing.id
                )
                if refreshed is None:
                    raise EntitiesServiceException(
                        "entity_update_lost", "Entity vanished after update"
                    )
                await session.commit()
                return refreshed
            await session.commit()
            return existing

        try:
            new_id = await self.repo.insert(
                session,
                user_id=user_id,
                kind=kind,
                name=name_stripped,
                slug=slug,
                description=description,
                attributes=attributes,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise EntitiesServiceException(
                "entity_insert_failed", str(exc)
            ) from exc

        row = await self.repo.get_by_id(session, user_id=user_id, entity_id=new_id)
        if row is None:
            raise EntitiesServiceException(
                "entity_insert_lost", "Newly inserted entity not found"
            )
        return row

    async def update(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        entity_id: UUID,
        name: str | None = None,
        description: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> EntityRow:
        n = await self.repo.update(
            session,
            entity_id=entity_id,
            user_id=user_id,
            name=name,
            description=description,
            attributes=attributes,
        )
        if n == 0:
            raise EntitiesNotFoundException(
                "entity_not_found", "No entity with that id for this user"
            )
        await session.commit()
        row = await self.repo.get_by_id(
            session, user_id=user_id, entity_id=entity_id
        )
        if row is None:
            raise EntitiesServiceException(
                "entity_update_lost", "Entity vanished after update"
            )
        return row

    async def delete(
        self, session: AsyncSession, *, user_id: UUID, entity_id: UUID
    ) -> None:
        n = await self.repo.delete(
            session, entity_id=entity_id, user_id=user_id
        )
        if n == 0:
            raise EntitiesNotFoundException(
                "entity_not_found", "No entity with that id for this user"
            )
        await session.commit()

    async def merge_into(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        target_id: UUID,
        from_id: UUID,
    ) -> None:
        if target_id == from_id:
            raise EntitiesUnprocessableException(
                "merge_self", "Cannot merge an entity into itself"
            )
        target = await self.repo.get_by_id(
            session, user_id=user_id, entity_id=target_id
        )
        src = await self.repo.get_by_id(
            session, user_id=user_id, entity_id=from_id
        )
        if target is None or src is None:
            raise EntitiesNotFoundException(
                "entity_not_found", "Both entities must exist for this user"
            )
        if target.kind != src.kind:
            raise EntitiesUnprocessableException(
                "merge_kind_mismatch", "Cannot merge entities of different kinds"
            )
        try:
            await self.repo.repoint_links(
                session, from_entity_id=from_id, to_entity_id=target_id
            )
            await self.repo.delete(
                session, entity_id=from_id, user_id=user_id
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise EntitiesServiceException(
                "entity_merge_failed", str(exc)
            ) from exc

    async def list_memories_for(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        entity_id: UUID,
        limit: int = 100,
    ) -> list[UUID]:
        return await self.repo.list_memories_for_entity(
            session, user_id=user_id, entity_id=entity_id, limit=limit
        )

    # ---- Extraction (used internally by memory ingest) ----

    async def upsert_and_link(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        memory_item_ids: list[UUID],
        chunk_text: str,
    ) -> int:
        """
        Run LLM extraction on the chunk text, upsert each entity, and link every
        provided memory_item_id to the resulting entities.

        Returns the number of (memory_item, entity) edges inserted (best-effort).
        Caller is responsible for committing the transaction; this method only
        flushes.
        """
        if not chunk_text.strip() or not memory_item_ids:
            return 0
        try:
            extracted = await self.extractor_factory().extract(chunk_text)
        except Exception:
            # Extraction is best-effort. Memory ingest must never fail because
            # the LLM extractor was unreachable or returned garbage.
            return 0

        edges = 0
        for ee in extracted.as_entities():
            slug = slugify(ee.name)
            if not slug:
                continue
            existing = await self.repo.get_by_slug(
                session, user_id=user_id, kind=ee.kind, slug=slug
            )
            if existing is not None:
                entity_id = existing.id
            else:
                entity_id = await self.repo.insert(
                    session,
                    user_id=user_id,
                    kind=ee.kind,
                    name=ee.name.strip(),
                    slug=slug,
                    description=None,
                    attributes=None,
                )
            for mid in memory_item_ids:
                await self.repo.insert_link(
                    session, memory_item_id=mid, entity_id=entity_id
                )
                edges += 1
        return edges
