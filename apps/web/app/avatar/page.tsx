"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LuminaTopBar } from "../_components/LuminaTopBar";
import { authMe, type AuthUser } from "../_lib/auth";
import {
  avatarsCreate,
  avatarsDelete,
  avatarsGenerateImage,
  avatarsList,
  avatarsSetActive,
  avatarsUpdate,
  type Avatar,
} from "../_lib/avatars";
import { voiceListVoices } from "../_lib/voices";

export default function AvatarPage() {
  const router = useRouter();
  const [me, setMe] = useState<AuthUser | null>(null);
  const [items, setItems] = useState<Avatar[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string>("");
  const [isGenerating, setIsGenerating] = useState<boolean>(false);

  const [name, setName] = useState<string>("Lumina");
  const [imageUrl, setImageUrl] = useState<string>("");
  const [persona, setPersona] = useState<string>(
    "You are Lumina, a friendly and helpful personal assistant."
  );
  const [ttsVoice, setTtsVoice] = useState<string>("");
  const [voiceOptions, setVoiceOptions] = useState<string[]>([]);
  const [voicesEngine, setVoicesEngine] = useState<string>("");
  const [voicesConfigured, setVoicesConfigured] = useState<boolean>(false);
  const [voicesLoadError, setVoicesLoadError] = useState<string>("");

  const [prompt, setPrompt] = useState<string>(
    "portrait photo of a friendly futuristic assistant, soft studio lighting, high detail, centered, looking at camera"
  );
  const [negativePrompt, setNegativePrompt] = useState<string>(
    "blurry, low quality, extra fingers, bad hands, deformed, watermark, text, logo"
  );
  const [steps, setSteps] = useState<number>(24);
  const [cfgScale, setCfgScale] = useState<number>(6.5);
  const [width, setWidth] = useState<number>(768);
  const [height, setHeight] = useState<number>(768);
  const [seed, setSeed] = useState<number>(-1);

  const active = items.find((a) => a.id === activeId) ?? null;

  useEffect(() => {
    // Keep UI controls in sync with the currently-active avatar.
    const v =
      (active as any)?.voice_config?.voice ||
      (active as any)?.voice_config?.tts_voice ||
      "";
    setTtsVoice(String(v ?? ""));
  }, [active]);

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

  async function refreshVoices() {
    setVoicesLoadError("");
    try {
      const v = await voiceListVoices();
      setVoiceOptions(v.voices ?? []);
      setVoicesEngine(String(v.engine ?? ""));
      setVoicesConfigured(Boolean(v.configured));
    } catch (e: any) {
      setVoiceOptions([]);
      setVoicesEngine("");
      setVoicesConfigured(false);
      setVoicesLoadError(String(e?.message ?? e ?? "failed_to_load_voices"));
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
        voice_config: ttsVoice ? { voice: ttsVoice } : undefined,
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

  async function generateImage() {
    if (!activeId) {
      setError("Pick or create an avatar first");
      setStatus("error");
      return;
    }
    setStatus("loading");
    setError("");
    setIsGenerating(true);
    try {
      const res = await avatarsGenerateImage(activeId, {
        prompt,
        negative_prompt: negativePrompt || undefined,
        width,
        height,
        steps,
        cfg_scale: cfgScale,
        seed,
      });
      // Update local list so preview updates immediately.
      setItems((prev: Avatar[]) =>
        prev.map((a: Avatar) =>
          a.id === activeId ? { ...a, image_url: res.image_url } : a
        )
      );
      // Also refresh from the server so we reflect the persisted image_url.
      await refresh();
      setStatus("idle");
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "unknown_error"));
      setStatus("error");
    } finally {
      setIsGenerating(false);
    }
  }

  async function saveVoice() {
    if (!activeId) {
      setError("Pick or create an avatar first");
      setStatus("error");
      return;
    }
    setStatus("loading");
    setError("");
    try {
      await avatarsUpdate(activeId, {
        voice_config: ttsVoice ? { voice: ttsVoice } : null,
      });
      await refresh();
      setStatus("idle");
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "unknown_error"));
      setStatus("error");
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const u = await authMe();
        if (!u) {
          router.replace("/login");
          return;
        }
        setMe(u);
        await refresh();
        try {
          await refreshVoices();
        } catch {
          // ignore (voices list is optional; manual entry still works)
        }
      } catch {
        setError(
          "API unreachable (failed to fetch /auth/me). Is the API container running?"
        );
        setStatus("error");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main>
      <style>{`
        @keyframes luminaShimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
      `}</style>
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
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: "#666" }}>
                voice (TTS voice id)
              </span>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <select
                  value={ttsVoice}
                  onChange={(e: any) =>
                    setTtsVoice(String(e.target.value ?? ""))
                  }
                  disabled={voiceOptions.length === 0}
                  style={{ flex: 1 }}
                >
                  <option value="">(default)</option>
                  {voiceOptions.length === 0 ? (
                    <option value="" disabled>
                      (no voices found)
                    </option>
                  ) : null}
                  {voiceOptions.map((v: string) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => void refreshVoices()}
                  disabled={status === "loading"}
                >
                  Refresh voices
                </button>
              </div>
              <div style={{ fontSize: 12, color: "#666" }}>
                voices: {voiceOptions.length}{" "}
                {voicesEngine ? `• engine: ${voicesEngine}` : ""} •
                tts_configured: {voicesConfigured ? "yes" : "no"}
                {voicesLoadError ? ` • error: ${voicesLoadError}` : ""}
              </div>
              <input
                placeholder={
                  voicesEngine
                    ? `e.g. ${voicesEngine}: <voice id>`
                    : "e.g. en_US-lessac-medium / Samantha / 0 (speaker id)"
                }
                value={ttsVoice}
                onChange={(e: any) => setTtsVoice(e.target.value)}
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

        <section
          style={{
            marginTop: 16,
            padding: 16,
            border: "1px solid #ddd",
            borderRadius: 12,
            background: "#fafafa",
          }}
        >
          <div style={{ fontSize: 12, color: "#666" }}>Active voice</div>
          <div
            style={{
              display: "flex",
              gap: 10,
              alignItems: "flex-end",
              marginTop: 10,
            }}
          >
            <label style={{ display: "grid", gap: 6, flex: 1 }}>
              <span style={{ fontSize: 12, color: "#666" }}>voice</span>
              <select
                value={ttsVoice}
                onChange={(e: any) => setTtsVoice(String(e.target.value ?? ""))}
                disabled={voiceOptions.length === 0}
              >
                <option value="">(default)</option>
                {voiceOptions.length === 0 ? (
                  <option value="" disabled>
                    (no voices found)
                  </option>
                ) : null}
                {voiceOptions.map((v: string) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
              <input
                value={ttsVoice}
                onChange={(e: any) => setTtsVoice(e.target.value)}
                placeholder="(optional)"
              />
            </label>
            <button
              onClick={() => void saveVoice()}
              disabled={status === "loading" || !activeId}
            >
              {status === "loading" ? "Saving..." : "Save voice"}
            </button>
          </div>

          <div style={{ fontSize: 12, color: "#666" }}>Generate image</div>
          <div
            style={{
              marginTop: 10,
              display: "grid",
              gridTemplateColumns: "1.2fr 0.8fr",
              gap: 14,
              alignItems: "start",
            }}
          >
            <div style={{ display: "grid", gap: 10 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 12, color: "#666" }}>prompt</span>
                <textarea
                  value={prompt}
                  onChange={(e: any) => setPrompt(e.target.value)}
                  rows={4}
                />
              </label>
              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 12, color: "#666" }}>
                  negative_prompt
                </span>
                <textarea
                  value={negativePrompt}
                  onChange={(e: any) => setNegativePrompt(e.target.value)}
                  rows={3}
                />
              </label>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, 1fr)",
                  gap: 10,
                }}
              >
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: "#666" }}>steps</span>
                  <input
                    value={steps}
                    type="number"
                    onChange={(e: any) => setSteps(Number(e.target.value))}
                  />
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: "#666" }}>cfg_scale</span>
                  <input
                    value={cfgScale}
                    type="number"
                    step="0.1"
                    onChange={(e: any) => setCfgScale(Number(e.target.value))}
                  />
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: "#666" }}>seed</span>
                  <input
                    value={seed}
                    type="number"
                    onChange={(e: any) => setSeed(Number(e.target.value))}
                  />
                </label>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: 10,
                }}
              >
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: "#666" }}>width</span>
                  <input
                    value={width}
                    type="number"
                    onChange={(e: any) => setWidth(Number(e.target.value))}
                  />
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: "#666" }}>height</span>
                  <input
                    value={height}
                    type="number"
                    onChange={(e: any) => setHeight(Number(e.target.value))}
                  />
                </label>
              </div>
              <button
                onClick={() => void generateImage()}
                disabled={status === "loading" || !activeId}
              >
                {status === "loading"
                  ? "Generating..."
                  : "Generate for active avatar"}
              </button>
              <div style={{ fontSize: 12, color: "#6b7280" }}>
                Uses server-side `AVATAR_IMAGE_ENGINE` (recommended:
                `diffusers_sdxl` for SDXL base+refiner quality). Configure
                either Diffusers model paths or `A1111_BASE_URL` in `.env`.
              </div>
            </div>

            <div
              style={{
                border: "1px solid rgba(0,0,0,0.10)",
                borderRadius: 12,
                background: "white",
                padding: 12,
              }}
            >
              <div style={{ fontSize: 12, color: "#666" }}>Preview</div>
              <div style={{ marginTop: 10 }}>
                {isGenerating ? (
                  <div
                    style={{
                      width: "100%",
                      aspectRatio: "1 / 1",
                      borderRadius: 10,
                      background:
                        "linear-gradient(90deg, rgba(0,0,0,0.06) 0%, rgba(0,0,0,0.12) 50%, rgba(0,0,0,0.06) 100%)",
                      backgroundSize: "200% 100%",
                      animation: "luminaShimmer 1.4s ease-in-out infinite",
                      display: "grid",
                      placeItems: "center",
                      color: "#6b7280",
                      fontFamily: "ui-monospace, Menlo, monospace",
                    }}
                  >
                    generating…
                  </div>
                ) : active?.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={active.image_url}
                    alt={active.name}
                    style={{ width: "100%", borderRadius: 10 }}
                  />
                ) : (
                  <div
                    style={{
                      fontFamily: "ui-monospace, Menlo, monospace",
                      color: "#6b7280",
                    }}
                  >
                    (no image yet)
                  </div>
                )}
              </div>
              {active?.image_url ? (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 12, color: "#666" }}>image_url</div>
                  <input
                    readOnly
                    value={active.image_url}
                    style={{ width: "100%", fontSize: 12 }}
                  />
                </div>
              ) : null}
            </div>
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
