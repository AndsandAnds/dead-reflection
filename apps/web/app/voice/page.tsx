"use client";

/// <reference path="../../shims.d.ts" />

import { useEffect, useRef, useState } from "react";

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

function arrayBufferFromBase64(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export default function VoicePage() {
  const [status, setStatus] = useState<
    "idle" | "connecting" | "running" | "finalizing"
  >("idle");
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

  function cleanupAudio() {
    const worklet = workletRef.current;
    const source = sourceRef.current;
    const ctx = ctxRef.current;
    const stream = streamRef.current;

    workletRef.current = null;
    sourceRef.current = null;
    ctxRef.current = null;
    streamRef.current = null;
    outAnalyserRef.current = null;
    outGainRef.current = null;

    try {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    } catch {
      // ignore
    } finally {
      rafRef.current = null;
    }

    try {
      worklet?.disconnect();
      source?.disconnect();
      playbackRef.current?.stop();
      ctx?.close();
    } catch {
      // ignore
    }

    try {
      stream?.getTracks().forEach((t) => t.stop());
    } catch {
      // ignore
    }

    setInputLevel(0);
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

  async function start() {
    setStatus("connecting");
    // Barge-in: stop any previous playback immediately.
    try {
      playbackRef.current?.stop();
      playbackRef.current = null;
    } catch {
      // ignore
    }

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
          setMessages((prev: ChatMessage[]) => [
            ...prev,
            { role: "assistant", text: String(msg.text ?? "") },
          ]);
          // Quick audible + visual confirmation that output is working.
          playBeep();
          return;
        }
        if (msg.type === "tts_audio") {
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
          closeWs();
          cleanupAudio();
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
          closeWs();
          cleanupAudio();
          setStatus("idle");
        }
      } catch {
        // ignore
      }
    };

    ws.onclose = () => {
      // If the socket closes unexpectedly, clean up local capture resources.
      if (status !== "idle") {
        cleanupAudio();
        setStatus("idle");
      }
    };

    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("ws_error"));
    });

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    streamRef.current = stream;
    const ctx = new AudioContext();
    ctxRef.current = ctx;
    startOutputMeter(ctx);

    // Let the server know our capture sample rate (used for duration estimates).
    ws.send(JSON.stringify({ type: "hello", sample_rate: ctx.sampleRate }));

    const source = ctx.createMediaStreamSource(stream);
    sourceRef.current = source;

    // Capture via AudioWorklet (ScriptProcessorNode is deprecated).
    await ctx.audioWorklet.addModule("/mic-capture-worklet.js");
    const worklet = new AudioWorkletNode(ctx, "mic-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
    });
    workletRef.current = worklet;

    worklet.port.onmessage = (ev: MessageEvent) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      const frame = ev.data as Float32Array;
      if (!frame || (frame as any).length === 0) return;
      const now = performance.now();
      if (now - lastUiTickMsRef.current > 50) {
        lastUiTickMsRef.current = now;
        setInputLevel(clamp01(rmsLevel(frame) * 3.0));
      }
      const b64 = pcm16Base64FromFloat32(frame);
      ws.send(
        JSON.stringify({
          type: "audio_frame",
          sample_rate: ctx.sampleRate,
          pcm16le_b64: b64,
        })
      );
    };

    source.connect(worklet);
    setStatus("running");
  }

  function stop(cancel = false) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      closeWs();
      cleanupAudio();
      setStatus("idle");
      return;
    }

    if (cancel) {
      try {
        ws.send(JSON.stringify({ type: "cancel" }));
      } catch {
        // ignore
      }
      closeWs();
      cleanupAudio();
      setStatus("idle");
      return;
    }

    // End the capture, but keep the WS open until we receive the final transcript
    // + assistant message.
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
      </section>

      <section style={{ marginTop: 16, display: "flex", gap: 16 }}>
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
          style={{ marginTop: 8, fontFamily: "ui-monospace, Menlo, monospace" }}
        >
          {messages.length === 0 && !partial ? "(waiting for audio...)" : null}
          {messages.map((m: ChatMessage, idx: number) => (
            <div key={idx} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, color: "#666" }}>{m.role}</div>
              <div>{m.text}</div>
            </div>
          ))}
          {partial ? (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 12, color: "#666" }}>user (partial)</div>
              <div>{partial}</div>
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
