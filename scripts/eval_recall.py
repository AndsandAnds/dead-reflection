"""Recall eval harness for the G1 hybrid+rerank+decay rollout.

Loads a hand-labelled set of (user_id, query, expected_memory_id) pairs
and runs each through `MemoryService.search` under four configurations:

  1. baseline             — pure vector, no rerank, no decay
  2. +hybrid              — RRF fuse vector + BM25
  3. +hybrid +decay       — add time-decay multiplier
  4. +hybrid +decay +rerank — add cross-encoder rerank (target config)

Reports recall@5 and per-query P50 / P95 latency per configuration.

Usage:
    poetry run python scripts/eval_recall.py path/to/recall_eval_set.json

Eval-set JSON shape (one list of objects, each with these fields):
    [
        {
            "user_id": "uuid-string",
            "query": "rehearsal notes about the Hogs",
            "expected_memory_id": "uuid-string",
            "avatar_id": null,
            "notes": "optional human comment"
        },
        ...
    ]

The file path is meant to live in scripts/recall_eval_set.json — gitignore
it if the queries or expected ids leak private content.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from reflections.core.db import database_manager
from reflections.memory.service import MemoryService


@dataclass(frozen=True)
class EvalPair:
    user_id: UUID
    query: str
    expected_memory_id: UUID
    avatar_id: UUID | None
    notes: str | None


@dataclass(frozen=True)
class Config:
    label: str
    hybrid: bool
    decay: bool
    rerank: bool


CONFIGS: list[Config] = [
    Config("baseline", hybrid=False, decay=False, rerank=False),
    Config("+hybrid", hybrid=True, decay=False, rerank=False),
    Config("+hybrid +decay", hybrid=True, decay=True, rerank=False),
    Config("+hybrid +decay +rerank", hybrid=True, decay=True, rerank=True),
]


def _load_eval_set(path: Path) -> list[EvalPair]:
    raw = json.loads(path.read_text())
    pairs: list[EvalPair] = []
    for entry in raw:
        pairs.append(
            EvalPair(
                user_id=UUID(entry["user_id"]),
                query=entry["query"],
                expected_memory_id=UUID(entry["expected_memory_id"]),
                avatar_id=(
                    UUID(entry["avatar_id"])
                    if entry.get("avatar_id")
                    else None
                ),
                notes=entry.get("notes"),
            )
        )
    return pairs


async def _eval_one(
    svc: MemoryService,
    pair: EvalPair,
    cfg: Config,
    top_k: int,
) -> tuple[bool, float]:
    """Returns (hit_in_top_k, elapsed_seconds)."""
    started = time.perf_counter()
    async with database_manager.session() as session:
        rows = await svc.search(
            session,
            user_id=pair.user_id,
            avatar_id=pair.avatar_id,
            query=pair.query,
            top_k=top_k,
            include_user_scope=True,
            include_avatar_scope=pair.avatar_id is not None,
            include_cards=True,
            include_chunks=True,
            include_private=True,
            hybrid_enabled=cfg.hybrid,
            decay_enabled=cfg.decay,
            rerank_enabled=cfg.rerank,
        )
    elapsed = time.perf_counter() - started
    hit = any(r.id == pair.expected_memory_id for r in rows)
    return hit, elapsed


async def _run(eval_path: Path, top_k: int) -> int:
    pairs = _load_eval_set(eval_path)
    if not pairs:
        print(f"eval set is empty: {eval_path}", file=sys.stderr)
        return 1

    await database_manager.initialize()
    svc = MemoryService.create()

    print(
        f"loaded {len(pairs)} eval pairs from {eval_path.name}\n"
        f"running {len(CONFIGS)} configs at top_k={top_k}\n"
    )

    for cfg in CONFIGS:
        hits = 0
        latencies: list[float] = []
        for pair in pairs:
            hit, elapsed = await _eval_one(svc, pair, cfg, top_k=top_k)
            hits += 1 if hit else 0
            latencies.append(elapsed)

        recall = hits / len(pairs)
        p50_ms = statistics.median(latencies) * 1000.0
        # statistics.quantiles needs >=2 data points; guard for tiny eval sets.
        if len(latencies) >= 2:
            quantiles = statistics.quantiles(latencies, n=20)
            p95_ms = quantiles[18] * 1000.0
        else:
            p95_ms = p50_ms
        print(
            f"  {cfg.label:<28} recall@{top_k}={recall:.2%} "
            f"({hits}/{len(pairs)}) | "
            f"p50={p50_ms:6.1f}ms p95={p95_ms:6.1f}ms"
        )

    await database_manager.shutdown()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "eval_set",
        type=Path,
        help="Path to recall_eval_set.json",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Cutoff for recall@k (default: 5)",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.eval_set, args.top_k))


if __name__ == "__main__":
    raise SystemExit(main())
