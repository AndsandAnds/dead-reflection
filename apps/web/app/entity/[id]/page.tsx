"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LuminaTopBar } from "../../_components/LuminaTopBar";
import { MemoryCard } from "../../_components/MemoryCard";
import { authMe, type AuthUser } from "../../_lib/auth";
import {
  entityDelete,
  entityGet,
  entityUpdate,
  memorySearch,
  type Entity,
  type Memory,
} from "../../_lib/memory";

const KIND_LABEL: Record<Entity["kind"], string> = {
  person: "Person",
  place: "Place",
  event: "Event",
  topic: "Topic",
};

export default function EntityDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = params?.id;

  const [me, setMe] = useState<AuthUser | null>(null);
  const [entity, setEntity] = useState<Entity | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [editingName, setEditingName] = useState(false);
  const [editingDesc, setEditingDesc] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [draftDesc, setDraftDesc] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    if (!me || !id) return;
    let alive = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const ent = await entityGet(id);
        if (!alive) return;
        setEntity(ent);
        setDraftName(ent.name);
        setDraftDesc(ent.description ?? "");
        // Use memorySearch with entity_ids filter so we get linked_entities
        // attached + can leverage the same enrichment as Explore. We pass a
        // generic query because semantic ranking doesn't matter here — the
        // filter is what restricts the result.
        const r = await memorySearch({
          query: ent.name,
          user_id: me.id,
          top_k: 50,
          entity_ids: [ent.id],
        });
        if (alive) setMemories(r.items);
      } catch (e: any) {
        if (alive) setError(e?.message ?? "load failed");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [me, id]);

  async function saveName() {
    if (!entity) return;
    const next = draftName.trim();
    if (!next) return;
    try {
      const updated = await entityUpdate(entity.id, { name: next });
      setEntity(updated);
      setEditingName(false);
    } catch (e: any) {
      setError(e?.message ?? "save failed");
    }
  }

  async function saveDesc() {
    if (!entity) return;
    try {
      const updated = await entityUpdate(entity.id, {
        description: draftDesc.trim() || null,
      });
      setEntity(updated);
      setEditingDesc(false);
    } catch (e: any) {
      setError(e?.message ?? "save failed");
    }
  }

  async function removeEntity() {
    if (!entity) return;
    if (
      !confirm(
        `Delete "${entity.name}" and all its memory links? Memories themselves remain.`
      )
    )
      return;
    try {
      await entityDelete(entity.id);
      router.replace("/explore");
    } catch (e: any) {
      setError(e?.message ?? "delete failed");
    }
  }

  if (!me) {
    return <div style={{ padding: 24 }}>Loading...</div>;
  }

  return (
    <div style={{ background: "#fafafa", minHeight: "100vh" }}>
      <LuminaTopBar user={me} />
      <div style={{ maxWidth: 900, margin: "24px auto", padding: "0 16px" }}>
        {loading && <div style={{ color: "#6b7280" }}>Loading entity...</div>}
        {error && (
          <div
            style={{
              background: "#fef2f2",
              color: "#991b1b",
              padding: 10,
              borderRadius: 8,
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            {error}
          </div>
        )}
        {entity && (
          <>
            <div
              style={{
                background: "white",
                border: "1px solid rgba(0,0,0,0.06)",
                borderRadius: 12,
                padding: 18,
                marginBottom: 18,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  textTransform: "uppercase",
                  letterSpacing: 0.6,
                  color: "#6b7280",
                  fontWeight: 700,
                }}
              >
                {KIND_LABEL[entity.kind]}
              </div>
              {editingName ? (
                <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                  <input
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    style={{
                      flex: 1,
                      fontSize: 24,
                      fontWeight: 700,
                      padding: "4px 8px",
                      borderRadius: 8,
                      border: "1px solid rgba(0,0,0,0.12)",
                    }}
                  />
                  <button onClick={saveName} style={primaryBtn}>
                    Save
                  </button>
                  <button
                    onClick={() => {
                      setEditingName(false);
                      setDraftName(entity.name);
                    }}
                    style={ghostBtn}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div
                  style={{ display: "flex", alignItems: "center", gap: 8 }}
                >
                  <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700 }}>
                    {entity.name}
                  </h1>
                  <button
                    onClick={() => setEditingName(true)}
                    style={ghostBtn}
                  >
                    Rename
                  </button>
                  <div style={{ flex: 1 }} />
                  <button onClick={removeEntity} style={dangerBtn}>
                    Delete
                  </button>
                </div>
              )}
              <div style={{ marginTop: 12 }}>
                {editingDesc ? (
                  <>
                    <textarea
                      value={draftDesc}
                      onChange={(e) => setDraftDesc(e.target.value)}
                      placeholder="Add a description..."
                      style={{
                        width: "100%",
                        minHeight: 80,
                        padding: 10,
                        borderRadius: 8,
                        border: "1px solid rgba(0,0,0,0.12)",
                        fontFamily: "inherit",
                        fontSize: 14,
                      }}
                    />
                    <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                      <button onClick={saveDesc} style={primaryBtn}>
                        Save
                      </button>
                      <button
                        onClick={() => {
                          setEditingDesc(false);
                          setDraftDesc(entity.description ?? "");
                        }}
                        style={ghostBtn}
                      >
                        Cancel
                      </button>
                    </div>
                  </>
                ) : entity.description ? (
                  <div
                    style={{
                      fontSize: 14,
                      color: "#374151",
                      whiteSpace: "pre-wrap",
                    }}
                    onDoubleClick={() => setEditingDesc(true)}
                    title="Double-click to edit"
                  >
                    {entity.description}
                  </div>
                ) : (
                  <button
                    onClick={() => setEditingDesc(true)}
                    style={{
                      ...ghostBtn,
                      color: "#9ca3af",
                      borderStyle: "dashed",
                    }}
                  >
                    + Add description
                  </button>
                )}
              </div>
            </div>

            <h2
              style={{
                fontSize: 14,
                textTransform: "uppercase",
                letterSpacing: 0.6,
                color: "#6b7280",
                marginBottom: 8,
              }}
            >
              Linked memories ({memories.length})
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {memories.map((m) => (
                <MemoryCard
                  key={m.id}
                  memory={m}
                  onUpdated={(u) =>
                    setMemories((prev) =>
                      prev.map((p) => (p.id === u.id ? u : p))
                    )
                  }
                  onDeleted={(mid) =>
                    setMemories((prev) => prev.filter((p) => p.id !== mid))
                  }
                />
              ))}
              {memories.length === 0 && (
                <div
                  style={{
                    background: "white",
                    border: "1px dashed rgba(0,0,0,0.12)",
                    borderRadius: 12,
                    padding: 24,
                    color: "#6b7280",
                    fontSize: 14,
                    textAlign: "center",
                  }}
                >
                  No memories link to this entity yet.
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: 8,
  border: "none",
  background: "linear-gradient(135deg, rgba(99,102,241,1), rgba(236,72,153,1))",
  color: "white",
  fontWeight: 600,
  fontSize: 13,
  cursor: "pointer",
};

const ghostBtn: React.CSSProperties = {
  padding: "4px 10px",
  borderRadius: 8,
  border: "1px solid rgba(0,0,0,0.12)",
  background: "white",
  color: "#374151",
  fontSize: 12,
  cursor: "pointer",
};

const dangerBtn: React.CSSProperties = {
  padding: "4px 10px",
  borderRadius: 8,
  border: "1px solid rgba(220,38,38,0.25)",
  background: "white",
  color: "#dc2626",
  fontSize: 12,
  cursor: "pointer",
};
