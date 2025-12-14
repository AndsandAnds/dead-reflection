"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LuminaTopBar } from "../_components/LuminaTopBar";
import { authMe, type AuthUser } from "../_lib/auth";
import {
  avatarsCreate,
  avatarsDelete,
  avatarsList,
  avatarsSetActive,
  type Avatar,
} from "../_lib/avatars";

export default function AvatarPage() {
  const router = useRouter();
  const [me, setMe] = useState<AuthUser | null>(null);
  const [items, setItems] = useState<Avatar[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string>("");

  const [name, setName] = useState<string>("Lumina");
  const [imageUrl, setImageUrl] = useState<string>("");
  const [persona, setPersona] = useState<string>(
    "You are Lumina, a friendly and helpful personal assistant."
  );

  const active = items.find((a) => a.id === activeId) ?? null;

  async function refresh() {
    setStatus("loading");
    setError("");
    try {
      const res = await avatarsList();
      setItems(res.items ?? []);
      setActiveId(res.active_avatar_id ?? null);
      setStatus("idle");
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "unknown_error"));
      setStatus("error");
    }
  }

  async function create() {
    setStatus("loading");
    setError("");
    try {
      await avatarsCreate({
        name,
        image_url: imageUrl || undefined,
        persona_prompt: persona || undefined,
        set_active: true,
      });
      await refresh();
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "unknown_error"));
      setStatus("error");
    }
  }

  async function setActive(id: string | null) {
    setStatus("loading");
    setError("");
    try {
      await avatarsSetActive(id);
      await refresh();
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "unknown_error"));
      setStatus("error");
    }
  }

  async function remove(id: string) {
    setStatus("loading");
    setError("");
    try {
      await avatarsDelete(id);
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
        <h1 style={{ marginTop: 0 }}>Avatar</h1>
        <p style={{ color: "#444" }}>
          Create an avatar image + persona. The Voice page will animate it while
          Lumina speaks.
        </p>

        {error ? (
          <div style={{ marginTop: 12, color: "#b91c1c" }}>error: {error}</div>
        ) : null}

        <section
          style={{
            marginTop: 14,
            padding: 16,
            border: "1px solid #ddd",
            borderRadius: 12,
            background: "#fafafa",
          }}
        >
          <div style={{ fontSize: 12, color: "#666" }}>Create</div>
          <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: "#666" }}>name</span>
              <input
                value={name}
                onChange={(e: any) => setName(e.target.value)}
              />
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: "#666" }}>image_url</span>
              <input
                placeholder="https://… (or leave blank for placeholder)"
                value={imageUrl}
                onChange={(e: any) => setImageUrl(e.target.value)}
              />
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: "#666" }}>
                persona_prompt
              </span>
              <textarea
                value={persona}
                onChange={(e: any) => setPersona(e.target.value)}
                rows={6}
              />
            </label>
            <button
              onClick={() => void create()}
              disabled={status === "loading"}
            >
              {status === "loading" ? "Saving..." : "Create + set active"}
            </button>
          </div>
        </section>

        <section style={{ marginTop: 16 }}>
          <div style={{ fontSize: 12, color: "#666" }}>
            Avatars ({items.length}){" "}
            {active ? (
              <span style={{ marginLeft: 8 }}>active: {active.name}</span>
            ) : null}
          </div>
          {items.length === 0 ? (
            <div
              style={{
                marginTop: 8,
                fontFamily: "ui-monospace, Menlo, monospace",
              }}
            >
              (no avatars yet)
            </div>
          ) : (
            <ul style={{ marginTop: 12, paddingLeft: 16 }}>
              {items.map((a) => (
                <li key={a.id} style={{ marginBottom: 12 }}>
                  <div
                    style={{
                      display: "flex",
                      gap: 10,
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 700 }}>
                        {a.name}{" "}
                        {a.id === activeId ? (
                          <span style={{ color: "#059669" }}>(active)</span>
                        ) : null}
                      </div>
                      <div style={{ fontSize: 12, color: "#666" }}>{a.id}</div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        onClick={() => void setActive(a.id)}
                        disabled={status === "loading" || a.id === activeId}
                      >
                        Set active
                      </button>
                      <button
                        onClick={() => void remove(a.id)}
                        disabled={status === "loading"}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div style={{ marginTop: 10 }}>
            <button
              onClick={() => void setActive(null)}
              disabled={status === "loading" || !activeId}
            >
              Clear active avatar
            </button>
          </div>
        </section>
      </div>
    </main>
  );
}
