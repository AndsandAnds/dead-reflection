"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DateRangePicker } from "../_components/DateRangePicker";
import { EntityChip } from "../_components/EntityChip";
import { LuminaTopBar } from "../_components/LuminaTopBar";
import { MemoryCard } from "../_components/MemoryCard";
import { SearchBar } from "../_components/SearchBar";
import { authMe, type AuthUser } from "../_lib/auth";
import {
  entitiesList,
  memoryInspect,
  memorySearch,
  type Entity,
  type EntityKind,
  type Memory,
} from "../_lib/memory";

type Mode = "browse" | "search";
type KindFilter = "any" | "card" | "chunk";

const ENTITY_KINDS: EntityKind[] = ["person", "place", "event", "topic"];

export default function ExplorePage() {
  const router = useRouter();
  const [me, setMe] = useState<AuthUser | null>(null);
  const [items, setItems] = useState<Memory[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [mode, setMode] = useState<Mode>("browse");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("any");
  const [from, setFrom] = useState<string | null>(null);
  const [to, setTo] = useState<string | null>(null);
  const [activeEntityId, setActiveEntityId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initial auth check.
  useEffect(() => {
    let alive = true;
    (async () => {
      const u = await authMe();
      if (!alive) return;
      if (!u) {
        router.replace("/login");
        return;
      }
      setMe(u);
    })();
    return () => {
      alive = false;
    };
  }, [router]);

  // Load entity sidebar once.
  useEffect(() => {
    if (!me) return;
    let alive = true;
    (async () => {
      try {
        const r = await entitiesList({ limit: 500 });
        if (alive) setEntities(r.items);
      } catch {
        /* sidebar is non-critical */
      }
    })();
    return () => {
      alive = false;
    };
  }, [me]);

  // Reload results whenever filters/mode/me change.
  useEffect(() => {
    if (!me) return;
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me, mode, query, kind, from, to, activeEntityId]);

  async function reload() {
    if (!me) return;
    setLoading(true);
    setError(null);
    try {
      const date_from = from ? new Date(`${from}T00:00:00Z`).toISOString() : undefined;
      const date_to = to ? new Date(`${to}T23:59:59Z`).toISOString() : undefined;
      const entity_ids = activeEntityId ? [activeEntityId] : undefined;
      if (mode === "search" && query.trim()) {
        const r = await memorySearch({
          query: query.trim(),
          user_id: me.id,
          top_k: 50,
          include_cards: kind !== "chunk",
          include_chunks: kind !== "card",
          entity_ids,
          date_from,
          date_to,
        });
        setItems(r.items);
      } else {
        // Browse mode: server-side date/entity filters aren't on /inspect,
        // so we filter client-side after fetching a large page.
        const r = await memoryInspect(me.id, {
          limit: 200,
          kind: kind === "any" ? "any" : kind,
        });
        let out = r.items;
        if (from) {
          const ts = new Date(`${from}T00:00:00Z`).getTime();
          out = out.filter((m) => new Date(m.created_at).getTime() >= ts);
        }
        if (to) {
          const ts = new Date(`${to}T23:59:59Z`).getTime();
          out = out.filter((m) => new Date(m.created_at).getTime() <= ts);
        }
        if (activeEntityId) {
          out = out.filter((m) =>
            m.linked_entities.some((e) => e.id === activeEntityId)
          );
        }
        setItems(out);
      }
    } catch (e: any) {
      setError(e?.message ?? "load failed");
    } finally {
      setLoading(false);
    }
  }

  const entitiesByKind = useMemo(() => {
    const m: Record<EntityKind, Entity[]> = {
      person: [],
      place: [],
      event: [],
      topic: [],
    };
    for (const e of entities) m[e.kind].push(e);
    return m;
  }, [entities]);

  if (!me) {
    return <div style={{ padding: 24 }}>Loading...</div>;
  }

  return (
    <div style={{ background: "#fafafa", minHeight: "100vh" }}>
      <LuminaTopBar user={me} />
      <div
        style={{
          maxWidth: 1200,
          margin: "24px auto",
          padding: "0 16px",
          display: "grid",
          gridTemplateColumns: "260px 1fr",
          gap: 24,
        }}
      >
        {/* Sidebar: entities */}
        <aside
          style={{
            background: "white",
            border: "1px solid rgba(0,0,0,0.06)",
            borderRadius: 12,
            padding: 14,
            position: "sticky",
            top: 78,
            alignSelf: "start",
            maxHeight: "calc(100vh - 100px)",
            overflowY: "auto",
          }}
        >
          <div
            style={{
              fontSize: 12,
              textTransform: "uppercase",
              letterSpacing: 0.6,
              color: "#6b7280",
              fontWeight: 700,
              marginBottom: 8,
            }}
          >
            Entities
          </div>
          {activeEntityId && (
            <button
              onClick={() => setActiveEntityId(null)}
              style={{
                width: "100%",
                marginBottom: 10,
                padding: "6px 10px",
                borderRadius: 8,
                border: "1px solid rgba(0,0,0,0.12)",
                background: "white",
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              ✕ Clear entity filter
            </button>
          )}
          {ENTITY_KINDS.map((k) => {
            const list = entitiesByKind[k];
            if (list.length === 0) return null;
            return (
              <div key={k} style={{ marginBottom: 14 }}>
                <div
                  style={{
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                    color: "#9ca3af",
                    marginBottom: 4,
                  }}
                >
                  {k}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {list.map((e) => (
                    <EntityChip
                      key={e.id}
                      entity={{
                        id: e.id,
                        kind: e.kind,
                        name: e.name,
                        slug: e.slug,
                      }}
                      onClick={() => setActiveEntityId(e.id)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
          {entities.length === 0 && (
            <div style={{ fontSize: 12, color: "#9ca3af" }}>
              No entities yet. Record memories with names, places, and topics —
              they'll show up here.
            </div>
          )}
        </aside>

        {/* Main: search + filters + results */}
        <main style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <SearchBar
            initial={query}
            onSearch={(q) => {
              setQuery(q);
              setMode("search");
            }}
            busy={loading}
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
              fontSize: 12,
              color: "#374151",
            }}
          >
            <div style={{ display: "flex", gap: 4 }}>
              {(["any", "card", "chunk"] as KindFilter[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setKind(k)}
                  style={{
                    padding: "4px 10px",
                    borderRadius: 8,
                    border: "1px solid rgba(0,0,0,0.12)",
                    background: kind === k ? "#111827" : "white",
                    color: kind === k ? "white" : "#374151",
                    cursor: "pointer",
                    fontSize: 12,
                    textTransform: "capitalize",
                  }}
                >
                  {k}
                </button>
              ))}
            </div>
            <DateRangePicker
              from={from}
              to={to}
              onChange={(f, t) => {
                setFrom(f);
                setTo(t);
              }}
            />
            {mode === "search" && (
              <button
                onClick={() => {
                  setMode("browse");
                  setQuery("");
                }}
                style={{
                  padding: "4px 10px",
                  borderRadius: 8,
                  border: "1px solid rgba(0,0,0,0.12)",
                  background: "white",
                  fontSize: 12,
                  cursor: "pointer",
                }}
              >
                ✕ Clear search
              </button>
            )}
            <div style={{ flex: 1 }} />
            <div style={{ color: "#6b7280" }}>
              {loading
                ? "loading..."
                : `${items.length} ${items.length === 1 ? "memory" : "memories"}`}
            </div>
          </div>

          {error && (
            <div
              style={{
                background: "#fef2f2",
                color: "#991b1b",
                padding: 10,
                borderRadius: 8,
                fontSize: 13,
              }}
            >
              {error}
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {items.map((m) => (
              <MemoryCard
                key={m.id}
                memory={m}
                onUpdated={(updated) =>
                  setItems((prev) =>
                    prev.map((p) => (p.id === updated.id ? updated : p))
                  )
                }
                onDeleted={(id) =>
                  setItems((prev) => prev.filter((p) => p.id !== id))
                }
                onEntityClick={(eid) => setActiveEntityId(eid)}
              />
            ))}
            {!loading && items.length === 0 && (
              <div
                style={{
                  background: "white",
                  border: "1px dashed rgba(0,0,0,0.12)",
                  borderRadius: 12,
                  padding: 28,
                  textAlign: "center",
                  color: "#6b7280",
                  fontSize: 14,
                }}
              >
                Nothing here yet — try clearing filters or recording a memory.
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
