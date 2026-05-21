"use client";

import { useState } from "react";

import type { Memory } from "../_lib/memory";
import { memoryDelete, memoryPatch } from "../_lib/memory";
import { EntityChip } from "./EntityChip";

export function MemoryCard({
  memory,
  onUpdated,
  onDeleted,
  onEntityClick,
}: {
  memory: Memory;
  onUpdated?: (m: Memory) => void;
  onDeleted?: (id: string) => void;
  onEntityClick?: (entityId: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memory.content);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const updated = await memoryPatch(memory.id, draft.trim());
      setEditing(false);
      onUpdated?.(updated);
    } catch (e: any) {
      setError(e?.message ?? "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm("Delete this memory? This cannot be undone.")) return;
    setBusy(true);
    setError(null);
    try {
      await memoryDelete(memory.user_id, [memory.id]);
      onDeleted?.(memory.id);
    } catch (e: any) {
      setError(e?.message ?? "delete failed");
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        background: "white",
        border: "1px solid rgba(0,0,0,0.06)",
        borderRadius: 12,
        padding: "14px 16px",
        boxShadow: "0 1px 2px rgba(0,0,0,0.03)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 11,
          color: "#6b7280",
        }}
      >
        <span
          style={{
            textTransform: "uppercase",
            letterSpacing: 0.5,
            fontWeight: 700,
            // Memory kinds are both green; card (high-signal) is deeper.
            color: memory.kind === "card" ? "#15803d" : "#16a34a",
          }}
        >
          {memory.kind}
        </span>
        <span>·</span>
        <span>{new Date(memory.created_at).toLocaleString()}</span>
        <span>·</span>
        <span>{memory.scope}</span>
        <div style={{ flex: 1 }} />
        {!editing && (
          <>
            <button onClick={() => setEditing(true)} style={ghostBtn}>
              Edit
            </button>
            <button onClick={remove} disabled={busy} style={dangerBtn}>
              Delete
            </button>
          </>
        )}
      </div>

      {editing ? (
        <>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            style={{
              width: "100%",
              minHeight: 80,
              padding: 10,
              borderRadius: 8,
              border: "1px solid rgba(0,0,0,0.12)",
              fontFamily: "inherit",
              fontSize: 14,
              resize: "vertical",
            }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={save} disabled={busy || !draft.trim()} style={primaryBtn}>
              {busy ? "Saving..." : "Save"}
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setDraft(memory.content);
                setError(null);
              }}
              style={ghostBtn}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <div
          style={{
            fontSize: 14,
            lineHeight: 1.5,
            color: "#111827",
            whiteSpace: "pre-wrap",
          }}
        >
          {memory.content}
        </div>
      )}

      {error && (
        <div style={{ color: "#b91c1c", fontSize: 12 }}>{error}</div>
      )}

      {memory.linked_entities.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {memory.linked_entities.map((e) => (
            <EntityChip
              key={e.id}
              entity={e}
              onClick={onEntityClick ? () => onEntityClick(e.id) : undefined}
            />
          ))}
        </div>
      )}
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
