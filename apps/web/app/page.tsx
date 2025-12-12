export default function Home() {
  const apiBase =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  return (
    <main style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ marginTop: 0 }}>Reflections — Local Avatar AI</h1>
      <p style={{ color: "#444" }}>
        UI is running. Next step: realtime voice (mic streaming) + FastAPI
        WebSocket.
      </p>

      <section
        style={{
          padding: 16,
          border: "1px solid #ddd",
          borderRadius: 12,
          background: "#fafafa",
        }}
      >
        <div style={{ fontSize: 12, color: "#666" }}>API base URL</div>
        <div
          style={{
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          }}
        >
          {apiBase}
        </div>
      </section>

      <section style={{ marginTop: 16 }}>
        <a href="/voice">Go to Voice MVP</a>
      </section>
    </main>
  );
}
