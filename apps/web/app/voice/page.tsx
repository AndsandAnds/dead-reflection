"use client";

/// <reference path="../../shims.d.ts" />

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { LuminaTopBar } from "../_components/LuminaTopBar";
import { TalkingAvatar } from "../_components/TalkingAvatar";
import { authMe, type AuthUser } from "../_lib/auth";
import { avatarsList, type Avatar } from "../_lib/avatars";

type ChatMessage = { role: "user" | "assistant" | "system"; text: string };

function clamp01(x: number): number {
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

function rmsLevel(frame: Float32Array): number {
  let sumSq = 0;
  for (let i = 0; i < frame.length; i++) sumSq += frame[i] * frame[i];
  const mean = frame.length ? sumSq / frame.length : 0;
  return Math.sqrt(mean);
}

function pcm16leBufferFromFloat32(input: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

function arrayBufferFromBase64(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export default function VoicePage() {
  const router = useRouter();
  const [status, setStatus] = useState<
    "disconnected" | "connecting" | "idle" | "running" | "finalizing"
  >("idle");
  const [me, setMe] = useState<AuthUser | null>(null);
  const [activeAvatar, setActiveAvatar] = useState<Avatar | null>(null);
  const [partial, setPartial] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputLevel, setInputLevel] = useState<number>(0);
  const [outputLevel, setOutputLevel] = useState<number>(0);
  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const outAnalyserRef = useRef<AnalyserNode | null>(null);
  const outGainRef = useRef<GainNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastUiTickMsRef = useRef<number>(0);
  const playbackRef = useRef<AudioBufferSourceNode | null>(null);
  const workletLoadedRef = useRef<boolean>(false);
  const statusRef = useRef<string>("idle");
  const lastSpeechMsRef = useRef<number>(0);
  const startedMsRef = useRef<number>(0);
  const ttsQueueRef = useRef<AudioBuffer[]>([]);
  const ttsPlayingRef = useRef<boolean>(false);
  const ttsSawChunksRef = useRef<boolean>(false);
  const assistantStreamingRef = useRef<boolean>(false);
  const assistantHadDeltaRef = useRef<boolean>(false);
  const finalizeSentRef = useRef<boolean>(false);
  const spaceDownRef = useRef<boolean>(false);
  const startInFlightRef = useRef<boolean>(false);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(() => {
    (async () => {
      const u = await authMe();
      if (!u) {
        router.replace("/login");
        return;
      }
      setMe(u);
      try {
        const res = await avatarsList();
        const activeId = (u as any)?.active_avatar_id ?? res.active_avatar_id;
        const active = (res.items ?? []).find((a) => a.id === activeId) ?? null;
        setActiveAvatar(active);
      } catch {
        // ignore (avatars are optional)
      }
    })();
  }, [router]);

  useEffect(() => {
    const isEditableTarget = (t: EventTarget | null): boolean => {
      const el = t as HTMLElement | null;
      if (!el) return false;
      const tag = (el.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select")
        return true;
      return Boolean((el as any).isContentEditable);
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      if (isEditableTarget(e.target)) return;
      // Prevent page scroll on Space.
      e.preventDefault();
      if (spaceDownRef.current) return;
      spaceDownRef.current = true;

      const st = statusRef.current;
      if (st === "idle" || st === "disconnected") {
        void start();
      }
    };

    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      if (!spaceDownRef.current) return;
      spaceDownRef.current = false;

      const st = statusRef.current;
      if (st === "running") {
        stop(false);
      }
    };

    window.addEventListener("keydown", onKeyDown, { passive: false });
    window.addEventListener("keyup", onKeyUp, { passive: false });
    return () => {
      window.removeEventListener("keydown", onKeyDown as any);
      window.removeEventListener("keyup", onKeyUp as any);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const apiBase =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const wsUrl = apiBase.replace(/^http/, "ws") + "/ws/voice";

  function startOutputMeter(ctx: AudioContext) {
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    const gain = ctx.createGain();
    gain.gain.value = 1.0;
    gain.connect(analyser);
    analyser.connect(ctx.destination);
    outAnalyserRef.current = analyser;
    outGainRef.current = gain;

    const buf = new Float32Array(analyser.fftSize);
    const tick = () => {
      const a = outAnalyserRef.current;
      if (!a) return;
      a.getFloatTimeDomainData(buf);
      const now = performance.now();
      if (now - lastUiTickMsRef.current > 50) {
        lastUiTickMsRef.current = now;
        setOutputLevel(clamp01(rmsLevel(buf) * 3.0));
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
  }

  function playBeep() {
    const ctx = ctxRef.current;
    const gain = outGainRef.current;
    if (!ctx || !gain) return;

    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 880;

    const env = ctx.createGain();
    env.gain.value = 0.0;
    osc.connect(env);
    env.connect(gain);

    const t0 = ctx.currentTime;
    env.gain.setValueAtTime(0.0, t0);
    env.gain.linearRampToValueAtTime(0.12, t0 + 0.01);
    env.gain.linearRampToValueAtTime(0.0, t0 + 0.12);
    osc.start(t0);
    osc.stop(t0 + 0.13);
  }

  function cleanupCapture() {
    const worklet = workletRef.current;
    const source = sourceRef.current;
    const stream = streamRef.current;

    workletRef.current = null;
    sourceRef.current = null;
    streamRef.current = null;

    try {
      worklet?.disconnect();
      source?.disconnect();
    } catch {
      // ignore
    }

    try {
      stream?.getTracks().forEach((t) => t.stop());
    } catch {
      // ignore
    }

    setInputLevel(0);
  }

  function cleanupAll() {
    const ctx = ctxRef.current;
    ctxRef.current = null;
    outAnalyserRef.current = null;
    outGainRef.current = null;

    try {
      playbackRef.current?.stop();
      playbackRef.current = null;
    } catch {
      // ignore
    }
    ttsQueueRef.current = [];
    ttsPlayingRef.current = false;
    ttsSawChunksRef.current = false;

    try {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    } catch {
      // ignore
    } finally {
      rafRef.current = null;
    }

    try {
      ctx?.close();
    } catch {
      // ignore
    }
    setOutputLevel(0);
  }

  function closeWs() {
    const ws = wsRef.current;
    wsRef.current = null;
    if (!ws) return;
    try {
      ws.close();
    } catch {
      // ignore
    }
  }

  async function ensureSocket(): Promise<WebSocket | null> {
    const existing = wsRef.current;
    if (existing && existing.readyState === WebSocket.OPEN) return existing;

    setStatus("connecting");
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(String(ev.data));
        if (msg.type === "ready") return;
        if (msg.type === "partial_transcript") {
          setPartial(String(msg.text ?? ""));
          return;
        }
        if (msg.type === "final_transcript") {
          setPartial("");
          setMessages((prev: ChatMessage[]) => [
            ...prev,
            { role: "user", text: String(msg.text ?? "") },
          ]);
          return;
        }
        if (msg.type === "assistant_message") {
          const finalText = String(msg.text ?? "");
          setMessages((prev: ChatMessage[]) => {
            // Idempotency guard: if the backend repeats the final message,
            // don't append a duplicate.
            if (
              prev.length > 0 &&
              prev[prev.length - 1]?.role === "assistant" &&
              prev[prev.length - 1]?.text === finalText
            ) {
              return prev;
            }
            if (
              assistantHadDeltaRef.current &&
              prev.length > 0 &&
              prev[prev.length - 1]?.role === "assistant"
            ) {
              return [
                ...prev.slice(0, -1),
                { role: "assistant", text: finalText },
              ];
            }
            return [...prev, { role: "assistant", text: finalText }];
          });
          assistantStreamingRef.current = false;
          assistantHadDeltaRef.current = false;
          return;
        }
        if (msg.type === "assistant_delta") {
          const delta = String(msg.delta ?? "");
          if (!delta) return;
          assistantStreamingRef.current = true;
          assistantHadDeltaRef.current = true;
          setMessages((prev: ChatMessage[]) => {
            if (
              assistantStreamingRef.current &&
              prev.length > 0 &&
              prev[prev.length - 1]?.role === "assistant"
            ) {
              const last = prev[prev.length - 1]!;
              return [
                ...prev.slice(0, -1),
                { role: "assistant", text: last.text + delta },
              ];
            }
            return [...prev, { role: "assistant", text: delta }];
          });
          return;
        }
        if (msg.type === "tts_chunk") {
          const ctx = ctxRef.current;
          const gain = outGainRef.current;
          if (!ctx || !gain) return;

          ttsSawChunksRef.current = true;
          const wavB64 = String(msg.wav_b64 ?? "");
          if (!wavB64) return;

          const enqueue = (audioBuffer: AudioBuffer) => {
            ttsQueueRef.current.push(audioBuffer);
            if (ttsPlayingRef.current) return;
            const playNext = () => {
              const next = ttsQueueRef.current.shift();
              if (!next) {
                ttsPlayingRef.current = false;
                return;
              }
              ttsPlayingRef.current = true;
              try {
                playbackRef.current?.stop();
              } catch {
                // ignore
              }
              const src = ctx.createBufferSource();
              src.buffer = next;
              src.connect(gain);
              playbackRef.current = src;
              src.onended = () => playNext();
              src.start();
            };
            playNext();
          };

          const buf = arrayBufferFromBase64(wavB64);
          ctx
            .decodeAudioData(buf.slice(0))
            .then((audioBuffer) => enqueue(audioBuffer))
            .catch(() => {
              // ignore decode errors
            });
          return;
        }
        if (msg.type === "tts_audio") {
          // If the server is sending chunked TTS, ignore the legacy single WAV to
          // avoid double playback.
          if (ttsSawChunksRef.current) return;
          const ctx = ctxRef.current;
          const gain = outGainRef.current;
          if (!ctx || !gain) return;

          const wavB64 = String(msg.wav_b64 ?? "");
          if (!wavB64) return;

          const buf = arrayBufferFromBase64(wavB64);
          ctx
            .decodeAudioData(buf.slice(0))
            .then((audioBuffer) => {
              // Stop any previous playback.
              try {
                playbackRef.current?.stop();
              } catch {
                // ignore
              }
              const src = ctx.createBufferSource();
              src.buffer = audioBuffer;
              src.connect(gain);
              playbackRef.current = src;
              src.start();
            })
            .catch(() => {
              // ignore decode errors
            });
          return;
        }
        if (msg.type === "done") {
          // Turn boundary: reset per-turn TTS chunk tracking.
          ttsSawChunksRef.current = false;
          assistantStreamingRef.current = false;
          assistantHadDeltaRef.current = false;
          finalizeSentRef.current = false;
          statusRef.current = "idle";
          setStatus("idle");
          return;
        }
        if (msg.type === "error") {
          setMessages((prev: ChatMessage[]) => [
            ...prev,
            { role: "system", text: String(msg.message ?? "error") },
          ]);
          return;
        }
        if (msg.type === "cancelled") {
          // Stop any queued/playing TTS immediately.
          try {
            playbackRef.current?.stop();
          } catch {
            // ignore
          } finally {
            playbackRef.current = null;
          }
          ttsQueueRef.current = [];
          ttsPlayingRef.current = false;
          ttsSawChunksRef.current = false;
          assistantStreamingRef.current = false;
          assistantHadDeltaRef.current = false;
          finalizeSentRef.current = false;
          statusRef.current = "idle";
          setStatus("idle");
        }
      } catch {
        // ignore
      }
    };

    ws.onclose = () => {
      cleanupCapture();
      cleanupAll();
      setStatus("disconnected");
    };

    const openOk = await new Promise<boolean>((resolve) => {
      const timeoutMs = 5000;
      const t = window.setTimeout(() => resolve(false), timeoutMs);

      ws.onopen = () => {
        window.clearTimeout(t);
        resolve(true);
      };
      ws.onerror = () => {
        window.clearTimeout(t);
        resolve(false);
      };
    });

    if (!openOk) {
      try {
        ws.close();
      } catch {
        // ignore
      }
      setMessages((prev: ChatMessage[]) => [
        ...prev,
        { role: "system", text: `ws_error: failed to connect to ${wsUrl}` },
      ]);
      setStatus("disconnected");
      return null;
    }

    setStatus("idle");
    return ws;
  }

  async function ensureAudioContext(): Promise<AudioContext> {
    const existing = ctxRef.current;
    if (existing) return existing;
    const ctx = new AudioContext();
    ctxRef.current = ctx;
    startOutputMeter(ctx);
    if (!workletLoadedRef.current) {
      await ctx.audioWorklet.addModule("/mic-capture-worklet.js");
      workletLoadedRef.current = true;
    }
    return ctx;
  }

  async function start() {
    // Avoid double-start / repeated gestures while permissions are pending.
    if (startInFlightRef.current) return;
    const st = statusRef.current;
    if (st === "running" || st === "connecting" || st === "finalizing") return;
    startInFlightRef.current = true;

    // Barge-in: stop any previous playback immediately.
    try {
      playbackRef.current?.stop();
      playbackRef.current = null;
    } catch {
      // ignore
    }

    try {
      const ws = await ensureSocket();
      if (!ws) return;

      // Reset per-turn guards.
      finalizeSentRef.current = false;

      // Barge-in semantics: if the backend is still finalizing a previous turn
      // (LLM/TTS), ask it to cancel any in-flight work.
      try {
        ws.send(JSON.stringify({ type: "cancel" }));
      } catch {
        // ignore
      }

      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
        });
      } catch (err: any) {
        const name = String(err?.name ?? "");
        const msg = String(err?.message ?? "");
        const isDenied =
          name === "NotAllowedError" ||
          name === "PermissionDeniedError" ||
          msg.toLowerCase().includes("permission denied");
        setMessages((prev: ChatMessage[]) => [
          ...prev,
          {
            role: "system",
            text: isDenied
              ? "mic_permission_denied: allow microphone access for this site (browser address bar/lock icon) and reload."
              : `mic_error: ${name || msg || "unknown_error"}`,
          },
        ]);
        statusRef.current = "idle";
        setStatus("idle");
        return;
      }

      streamRef.current = stream;
      const ctx = await ensureAudioContext();

      // Let the server know our capture sample rate (used for duration estimates).
      ws.send(JSON.stringify({ type: "hello", sample_rate: ctx.sampleRate }));

      const source = ctx.createMediaStreamSource(stream);
      sourceRef.current = source;

      // Capture via AudioWorklet (ScriptProcessorNode is deprecated).
      const worklet = new AudioWorkletNode(ctx, "mic-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 0,
        channelCount: 1,
      });
      workletRef.current = worklet;
      startedMsRef.current = performance.now();
      lastSpeechMsRef.current = startedMsRef.current;

      worklet.port.onmessage = (ev: MessageEvent) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        const frame = ev.data as Float32Array;
        if (!frame || (frame as any).length === 0) return;
        const lvl = rmsLevel(frame);
        const now = performance.now();
        if (now - lastUiTickMsRef.current > 50) {
          lastUiTickMsRef.current = now;
          setInputLevel(clamp01(lvl * 3.0));
        }

        // Simple endpointing (silence timer): if user is quiet for a bit, auto-end.
        // This keeps a push-to-talk UX (Start mic / Stop) but makes it feel more
        // "hands free" for short utterances.
        const speechThreshold = 0.02;
        if (lvl >= speechThreshold) lastSpeechMsRef.current = now;
        if (
          statusRef.current === "running" &&
          now - startedMsRef.current > 1200 &&
          now - lastSpeechMsRef.current > 900
        ) {
          stop(false);
          return;
        }

        // Prefer binary WS frames for audio (lower overhead than base64 JSON).
        // Apply basic backpressure by dropping frames if the socket buffer grows.
        if (ws.bufferedAmount > 1_000_000) return;
        const buf = pcm16leBufferFromFloat32(frame);
        ws.send(buf);
      };

      source.connect(worklet);
      statusRef.current = "running";
      setStatus("running");
    } finally {
      startInFlightRef.current = false;
    }
  }

  function stop(cancel = false) {
    // Make stop idempotent to avoid duplicate 'end' from the silence timer
    // before React state + statusRef update propagate.
    if (!cancel && finalizeSentRef.current) return;

    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      closeWs();
      cleanupCapture();
      cleanupAll();
      setStatus("disconnected");
      return;
    }

    if (cancel) {
      try {
        ws.send(JSON.stringify({ type: "cancel" }));
      } catch {
        // ignore
      }
      cleanupCapture();
      finalizeSentRef.current = false;
      setStatus("idle");
      return;
    }

    // End the capture, but keep the WS open until we receive the final transcript
    // + assistant message.
    finalizeSentRef.current = true;
    statusRef.current = "finalizing";
    setStatus("finalizing");
    try {
      ws.send(JSON.stringify({ type: "end" }));
    } catch {
      // ignore
    }

    // Stop mic capture immediately (no more frames), but keep output meter + WS.
    try {
      workletRef.current?.disconnect();
      sourceRef.current?.disconnect();
    } catch {
      // ignore
    }
    try {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    } catch {
      // ignore
    }
    workletRef.current = null;
    sourceRef.current = null;
    streamRef.current = null;
  }

  useEffect(() => {
    return () => {
      try {
        stop(true);
      } catch {
        // ignore
      }
      closeWs();
      cleanupAll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main>
      {me ? <LuminaTopBar user={me} /> : null}
      <div style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
        <h1 style={{ marginTop: 0 }}>Lumina</h1>
        <p style={{ color: "#444" }}>
          MVP voice streaming to FastAPI WebSocket (STT currently stubbed
          server-side).
        </p>

        <section style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {status !== "running" ? (
            <button
              onClick={start}
              disabled={status === "connecting" || status === "finalizing"}
            >
              {status === "connecting"
                ? "Connecting..."
                : status === "finalizing"
                ? "Finalizing..."
                : "Start mic"}
            </button>
          ) : (
            <>
              <button onClick={() => stop(false)}>Stop (transcribe)</button>
              <button onClick={() => stop(true)}>Cancel</button>
            </>
          )}
          <div style={{ fontSize: 12, color: "#666" }}>WS: {wsUrl}</div>
          <a href="/avatar" style={{ fontSize: 12 }}>
            Avatar
          </a>
          <a href="/memory" style={{ fontSize: 12 }}>
            Memory
          </a>
        </section>

        <section style={{ marginTop: 16, display: "flex", gap: 16 }}>
          <div style={{ width: 260 }}>
            <TalkingAvatar
              name={activeAvatar?.name ?? "Lumina"}
              imageUrl={activeAvatar?.image_url ?? null}
              level={outputLevel}
              size={220}
            />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: "#666" }}>Mic level</div>
            <div
              style={{
                marginTop: 6,
                height: 10,
                borderRadius: 999,
                background: "#e5e7eb",
                overflow: "hidden",
                border: "1px solid #ddd",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${Math.round(inputLevel * 100)}%`,
                  background: inputLevel > 0.6 ? "#ef4444" : "#3b82f6",
                  transition: "width 40ms linear",
                }}
              />
            </div>
          </div>

          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: "#666" }}>Output level</div>
            <div
              style={{
                marginTop: 6,
                height: 10,
                borderRadius: 999,
                background: "#e5e7eb",
                overflow: "hidden",
                border: "1px solid #ddd",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${Math.round(outputLevel * 100)}%`,
                  background: outputLevel > 0.6 ? "#ef4444" : "#10b981",
                  transition: "width 40ms linear",
                }}
              />
            </div>
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
          <div style={{ fontSize: 12, color: "#666" }}>Conversation</div>
          <div
            style={{
              marginTop: 8,
              fontFamily: "ui-monospace, Menlo, monospace",
            }}
          >
            {messages.length === 0 && !partial
              ? "(waiting for audio...)"
              : null}
            {messages.map((m: ChatMessage, idx: number) => (
              <div key={idx} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 12, color: "#666" }}>{m.role}</div>
                <div>{m.text}</div>
              </div>
            ))}
            {partial ? (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 12, color: "#666" }}>
                  user (partial)
                </div>
                <div>{partial}</div>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
