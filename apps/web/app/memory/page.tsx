"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LuminaTopBar } from "../_components/LuminaTopBar";
import { authMe, type AuthUser } from "../_lib/auth";

type MemoryItem = {
  id: string;
  user_id: string;
  avatar_id: string | null;
  scope: "user" | "avatar";
  kind: "card" | "chunk";
  content: string;
  created_at: string;
};

export default function MemoryPage() {
  const router = useRouter();
  const apiBase =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  const [me, setMe] = useState<AuthUser | null>(null);

  const defaultUserId =
    process.env.NEXT_PUBLIC_DEFAULT_USER_ID ??
    "00000000-0000-0000-0000-000000000001";
  const defaultAvatarId =
    process.env.NEXT_PUBLIC_DEFAULT_AVATAR_ID ??
    "00000000-0000-0000-0000-000000000002";

  const [userId, setUserId] = useState<string>(defaultUserId);
  const [avatarId, setAvatarId] = useState<string>(defaultAvatarId);
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [status, setStatus] = useState<
    "idle" | "loading" | "deleting" | "error"
  >("idle");
  const [error, setError] = useState<string>("");

  const selectedIds = Object.entries(selected)
    .filter(([, v]) => v)
    .map(([k]) => k);

  async function refresh() {
    setStatus("loading");
    setError("");
    try {
      const res = await fetch(`${apiBase}/memory/inspect`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          avatar_id: avatarId || null,
          limit: 100,
          offset: 0,
          include_user_scope: true,
          include_avatar_scope: true,
          include_cards: true,
          include_chunks: true,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const rows = Array.isArray(data?.items) ? data.items : [];
      setItems(rows);
      setSelected({});
      setStatus("idle");
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "unknown_error"));
      setStatus("error");
    }
  }

  async function deleteSelected() {
    if (selectedIds.length === 0) return;
    setStatus("deleting");
    setError("");
    try {
      const res = await fetch(`${apiBase}/memory/delete`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ user_id: userId, ids: selectedIds }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await refresh();
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "unknown_error"));
      setStatus("error");
    }
  }

  useEffect(() => {
    (async () => {
      const u = await authMe();
      if (!u) {
        router.replace("/login");
        return;
      }
      setMe(u);
      await refresh();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main>
      {me ? <LuminaTopBar user={me} /> : null}
      <div style={{ padding: 24, maxWidth: 980, margin: "0 auto" }}>
        <h1 style={{ marginTop: 0 }}>Memory</h1>
        <p style={{ color: "#444" }}>
          Inspect and delete episodic memories stored in Postgres (pgvector).
        </p>

        <section style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 12, color: "#666" }}>user_id</span>
            <input
              value={userId}
              onChange={(e: any) => setUserId(e.target.value)}
              style={{ width: 360 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 12, color: "#666" }}>avatar_id</span>
            <input
              value={avatarId}
              onChange={(e: any) => setAvatarId(e.target.value)}
              style={{ width: 360 }}
            />
          </label>
          <button onClick={refresh} disabled={status === "loading"}>
            {status === "loading" ? "Loading..." : "Refresh"}
          </button>
          <button
            onClick={deleteSelected}
            disabled={status === "deleting" || selectedIds.length === 0}
          >
            {status === "deleting"
              ? "Deleting..."
              : `Delete selected (${selectedIds.length})`}
          </button>
        </section>

        {error ? (
          <div style={{ marginTop: 12, color: "#b91c1c" }}>error: {error}</div>
        ) : null}

        <section
          style={{
            marginTop: 16,
            padding: 16,
            border: "1px solid #ddd",
            borderRadius: 12,
            background: "#fafafa",
          }}
        >
          <div style={{ fontSize: 12, color: "#666" }}>
            Items ({items.length})
          </div>
          {items.length === 0 ? (
            <div
              style={{
                marginTop: 8,
                fontFamily: "ui-monospace, Menlo, monospace",
              }}
            >
              (no items)
            </div>
          ) : (
            <ul style={{ marginTop: 12, paddingLeft: 16 }}>
              {items.map((it) => (
                <li key={it.id} style={{ marginBottom: 12 }}>
                  <label
                    style={{
                      display: "flex",
                      gap: 8,
                      alignItems: "flex-start",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={Boolean(selected[it.id])}
                      onChange={(e: any) =>
                        setSelected((prev) => ({
                          ...prev,
                          [it.id]: e.target.checked,
                        }))
                      }
                    />
                    <div>
                      <div style={{ fontSize: 12, color: "#666" }}>
                        {it.kind} / {it.scope} — {it.created_at} — {it.id}
                      </div>
                      <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>
                        {it.content}
                      </div>
                    </div>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}
