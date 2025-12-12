"use client";

import { useEffect, useRef, useState } from "react";

function pcm16Base64FromFloat32(input: Float32Array): string {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  const bytes = new Uint8Array(buffer);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

export default function VoicePage() {
  const [status, setStatus] = useState<"idle" | "connecting" | "running">(
    "idle"
  );
  const [partial, setPartial] = useState<string>("");
  const [bytesHeard, setBytesHeard] = useState<number>(0);
  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const procRef = useRef<ScriptProcessorNode | null>(null);

  const apiBase =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const wsUrl = apiBase.replace(/^http/, "ws") + "/ws/voice";

  async function start() {
    setStatus("connecting");

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(String(ev.data));
        if (msg.type === "ready") return;
        if (msg.type === "partial_transcript") {
          setPartial(String(msg.text ?? ""));
          setBytesHeard(Number(msg.bytes_received ?? 0));
        }
        if (msg.type === "cancelled") {
          stop();
        }
      } catch {
        // ignore
      }
    };

    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("ws_error"));
    });

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    const ctx = new AudioContext();
    ctxRef.current = ctx;

    const source = ctx.createMediaStreamSource(stream);
    sourceRef.current = source;

    // MVP: ScriptProcessor for capture. We'll move to AudioWorklet once protocol stabilizes.
    const proc = ctx.createScriptProcessor(1024, 1, 1);
    procRef.current = proc;

    proc.onaudioprocess = (e) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      const channel = e.inputBuffer.getChannelData(0);
      const b64 = pcm16Base64FromFloat32(channel);
      ws.send(
        JSON.stringify({
          type: "audio_frame",
          sample_rate: ctx.sampleRate,
          pcm16le_b64: b64,
        })
      );
    };

    source.connect(proc);
    proc.connect(ctx.destination);
    setStatus("running");
  }

  function stop() {
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "cancel" }));
      } catch {
        // ignore
      }
      ws.close();
    }

    const proc = procRef.current;
    const source = sourceRef.current;
    const ctx = ctxRef.current;
    procRef.current = null;
    sourceRef.current = null;
    ctxRef.current = null;

    try {
      proc?.disconnect();
      source?.disconnect();
      ctx?.close();
    } catch {
      // ignore
    }

    setStatus("idle");
  }

  useEffect(() => {
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ marginTop: 0 }}>Voice</h1>
      <p style={{ color: "#444" }}>
        MVP voice streaming to FastAPI WebSocket (STT currently stubbed
        server-side).
      </p>

      <section style={{ display: "flex", gap: 12, alignItems: "center" }}>
        {status !== "running" ? (
          <button onClick={start} disabled={status === "connecting"}>
            {status === "connecting" ? "Connecting..." : "Start mic"}
          </button>
        ) : (
          <button onClick={stop}>Stop</button>
        )}
        <div style={{ fontSize: 12, color: "#666" }}>WS: {wsUrl}</div>
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
        <div style={{ fontSize: 12, color: "#666" }}>Partial transcript</div>
        <div
          style={{ marginTop: 8, fontFamily: "ui-monospace, Menlo, monospace" }}
        >
          {partial || "(waiting for audio...) "}
        </div>
        <div style={{ marginTop: 8, fontSize: 12, color: "#666" }}>
          bytes_received: {bytesHeard}
        </div>
      </section>
    </main>
  );
}
