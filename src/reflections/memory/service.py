from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.memory.exceptions import (
    MemoryServiceException,
    MemoryUnprocessableException,
)
from reflections.memory.repository import MemoryRepository, MemoryRow
from reflections.memory.schemas import Turn

EMBEDDING_MODEL_ID = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def chunk_turns_by_window(turns: list[Turn], window: int) -> list[str]:
    """
    Decision #4: chunk raw memory by turns (3–6 turns typical).
    """
    if window < 2:
        raise ValueError("window must be >= 2")

    chunks: list[str] = []
    for i in range(0, len(turns), window):
        group = turns[i : i + window]
        text = "\n".join(f"{t.role}: {t.content}" for t in group)
        chunks.append(text)
    return chunks


def extract_memory_cards_heuristic(turns: list[Turn]) -> list[str]:
    """
    Heuristic v0: extract a few high-signal sentences.

    This is intentionally conservative; we’ll later replace or augment with
    a local LLM extractor (PydanticAI + Ollama) once the pipeline is stable.
    """
    joined = " ".join(
        t.content.strip() for t in turns if t.role in ("user", "assistant")
    )
    if not joined:
        return []

    candidates: list[str] = []
    needles = [
        "i like",
        "i prefer",
        "my ",
        "i am ",
        "i'm ",
        "we are ",
        "we're ",
        "we will ",
        "we want ",
    ]
    for sentence in joined.replace("\n", " ").split("."):
        s = sentence.strip()
        if not s:
            continue
        low = s.lower()
        if any(n in low for n in needles):
            candidates.append(s)

    # Deduplicate + cap
    dedup: list[str] = []
    seen = set()
    for c in candidates:
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(c)

    return dedup[:5]


@dataclass
class MemoryService:
    repository: MemoryRepository
    embedder: SentenceTransformer

    @classmethod
    def create(cls) -> MemoryService:
        # normalize_embeddings=True gives us cosine==dot if vectors are normalized
        embedder = SentenceTransformer(EMBEDDING_MODEL_ID)
        return cls(repository=MemoryRepository(), embedder=embedder)

    def embed_text(self, text: str) -> list[float]:
        vec = self.embedder.encode([text], normalize_embeddings=True)[0].tolist()
        # Defensive: ensure normalized even if upstream settings change
        return _normalize([float(x) for x in vec])

    async def ingest_episodic(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        turns: list[Turn],
        chunk_turn_window: int,
    ) -> tuple[list[UUID], int, int]:
        """
        Hybrid memory: store cards + raw chunks.
        Hybrid scope: user-global cards + per-avatar episodic cards when avatar_id
        is set.
        """
        if not turns:
            raise MemoryUnprocessableException("No turns provided")

        stored_ids: list[UUID] = []
        cards = extract_memory_cards_heuristic(turns)
        raw_chunks = chunk_turns_by_window(turns, chunk_turn_window)

        try:
            # Memory cards
            for c in cards:
                scope = "avatar" if avatar_id else "user"
                emb = self.embed_text(c)
                stored_ids.append(
                    await self.repository.insert_item(
                        session,
                        user_id=user_id,
                        avatar_id=avatar_id,
                        scope=scope,
                        kind="card",
                        content=c,
                        embedding=emb,
                    )
                )

            # Raw chunks (always avatar-scoped if avatar_id exists, else user-scoped)
            for ch in raw_chunks:
                scope = "avatar" if avatar_id else "user"
                emb = self.embed_text(ch)
                stored_ids.append(
                    await self.repository.insert_item(
                        session,
                        user_id=user_id,
                        avatar_id=avatar_id,
                        scope=scope,
                        kind="chunk",
                        content=ch,
                        embedding=emb,
                    )
                )

            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise MemoryServiceException("Failed to ingest memory", str(exc)) from exc

        return stored_ids, len(cards), len(raw_chunks)

    async def search(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        query: str,
        top_k: int,
        include_user_scope: bool,
        include_avatar_scope: bool,
        include_cards: bool,
        include_chunks: bool,
    ) -> list[MemoryRow]:
        if not query.strip():
            raise MemoryUnprocessableException("Query is empty")

        try:
            q_emb = self.embed_text(query)
            return await self.repository.search(
                session,
                user_id=user_id,
                avatar_id=avatar_id,
                query_embedding=q_emb,
                top_k=top_k,
                include_user_scope=include_user_scope,
                include_avatar_scope=include_avatar_scope,
                include_cards=include_cards,
                include_chunks=include_chunks,
            )
        except MemoryUnprocessableException:
            raise
        except Exception as exc:
            raise MemoryServiceException("Failed to search memory", str(exc)) from exc

    async def inspect(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        limit: int,
        offset: int,
        include_user_scope: bool,
        include_avatar_scope: bool,
        include_cards: bool,
        include_chunks: bool,
    ) -> list[MemoryRow]:
        try:
            return await self.repository.list_items(
                session,
                user_id=user_id,
                avatar_id=avatar_id,
                limit=limit,
                offset=offset,
                include_user_scope=include_user_scope,
                include_avatar_scope=include_avatar_scope,
                include_cards=include_cards,
                include_chunks=include_chunks,
            )
        except Exception as exc:
            raise MemoryServiceException("Failed to inspect memory", str(exc)) from exc

    async def delete(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        ids: list[UUID],
    ) -> int:
        if not ids:
            raise MemoryUnprocessableException("No ids provided")
        try:
            deleted = await self.repository.delete_items(
                session, user_id=user_id, ids=ids
            )
            await session.commit()
            return deleted
        except Exception as exc:
            await session.rollback()
            raise MemoryServiceException("Failed to delete memory", str(exc)) from exc
