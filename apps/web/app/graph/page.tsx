"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { DateRangePicker } from "../_components/DateRangePicker";
import { LuminaTopBar } from "../_components/LuminaTopBar";
import { authMe, type AuthUser } from "../_lib/auth";
import {
  memoryGraph,
  type GraphResponse,
  type GraphNode,
} from "../_lib/memory";

// react-force-graph uses Canvas + DOM measurement; SSR-disable it.
const ForceGraph2D: any = dynamic(
  () => import("react-force-graph-2d").then((m) => m.default),
  { ssr: false }
);

type FGNode = GraphNode & {
  x?: number;
  y?: number;
  color: string;
  size: number;
};

// Palette — keep in sync with EntityChip.tsx KIND_COLORS.
const COLOR_BY_KIND: Record<string, string> = {
  // Memory: two shades of green so cards (high-signal) read as deeper.
  memory_card: "#15803d",   // green-700
  memory_chunk: "#22c55e",  // green-500
  entity_person: "#ec4899", // hot pink
  entity_place: "#14b8a6",  // teal
  entity_event: "#f97316",  // orange
  entity_topic: "#eab308",  // marigold
};

function colorFor(kind: string): string {
  return COLOR_BY_KIND[kind] ?? "#6b7280";
}

export default function GraphPage() {
  const router = useRouter();
  const [me, setMe] = useState<AuthUser | null>(null);
  const [from, setFrom] = useState<string | null>(null);
  const [to, setTo] = useState<string | null>(null);
  const [data, setData] = useState<GraphResponse>({ nodes: [], edges: [] });
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number }>({ w: 800, h: 600 });

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
    if (!me) return;
    let alive = true;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const date_from = from ? new Date(`${from}T00:00:00Z`).toISOString() : undefined;
        const date_to = to ? new Date(`${to}T23:59:59Z`).toISOString() : undefined;
        const r = await memoryGraph({ date_from, date_to, limit_memories: 500 });
        if (alive) setData(r);
      } catch (e: any) {
        if (alive) setError(e?.message ?? "graph load failed");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [me, from, to]);

  // Resize the canvas to its wrapper.
  useEffect(() => {
    function measure() {
      if (!wrapRef.current) return;
      const r = wrapRef.current.getBoundingClientRect();
      setDims({ w: Math.max(400, r.width), h: Math.max(400, r.height) });
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [me]);

  const graphData = useMemo(() => {
    const nodes: FGNode[] = data.nodes.map((n) => ({
      ...n,
      color: colorFor(n.kind),
      // Entities are bigger anchors; memories are dots.
      size: n.kind.startsWith("entity_") ? 6 : 3,
    }));
    const links = data.edges.map((e) => ({
      source: e.source,
      target: e.target,
    }));
    return { nodes, links };
  }, [data]);

  if (!me) {
    return <div style={{ padding: 24 }}>Loading...</div>;
  }

  return (
    <div style={{ background: "#fafafa", minHeight: "100vh" }}>
      <LuminaTopBar user={me} />
      <div
        style={{
          maxWidth: 1400,
          margin: "24px auto",
          padding: "0 16px",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div
          style={{
            display: "flex",
            gap: 14,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>
            Knowledge graph
          </h1>
          <div style={{ color: "#6b7280", fontSize: 13 }}>
            {loading
              ? "loading..."
              : `${data.nodes.length} nodes, ${data.edges.length} edges`}
          </div>
          <div style={{ flex: 1 }} />
          <DateRangePicker
            from={from}
            to={to}
            onChange={(f, t) => {
              setFrom(f);
              setTo(t);
            }}
          />
        </div>

        <Legend />

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

        <div
          style={{
            display: "grid",
            gridTemplateColumns: selected ? "1fr 320px" : "1fr",
            gap: 14,
          }}
        >
          <div
            ref={wrapRef}
            style={{
              background: "white",
              border: "1px solid rgba(0,0,0,0.06)",
              borderRadius: 12,
              height: "70vh",
              minHeight: 500,
              overflow: "hidden",
            }}
          >
            {data.nodes.length === 0 && !loading ? (
              <div
                style={{
                  height: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#6b7280",
                  fontSize: 14,
                }}
              >
                No memories or entities yet in this range.
              </div>
            ) : (
              <ForceGraph2D
                graphData={graphData}
                width={dims.w}
                height={dims.h}
                nodeLabel={(n: FGNode) => `${n.kind}: ${n.label}`}
                nodeAutoColorBy={undefined}
                nodeColor={(n: FGNode) => n.color}
                nodeVal={(n: FGNode) => n.size}
                linkColor={() => "rgba(0,0,0,0.15)"}
                linkWidth={1}
                onNodeClick={(n: FGNode) => setSelected(n)}
                cooldownTicks={120}
                nodeCanvasObjectMode={() => "after"}
                nodeCanvasObject={(node: any, ctx: any, scale: number) => {
                  // Draw label only when zoomed in enough so the view stays clean.
                  if (scale < 1.4) return;
                  const label = node.label ?? "";
                  ctx.font = `${10 / scale}px sans-serif`;
                  ctx.fillStyle = "#111827";
                  ctx.textAlign = "center";
                  ctx.fillText(label, node.x, node.y + 8 / scale);
                }}
              />
            )}
          </div>

          {selected && (
            <aside
              style={{
                background: "white",
                border: "1px solid rgba(0,0,0,0.06)",
                borderRadius: 12,
                padding: 14,
                fontSize: 13,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 10,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                    fontWeight: 700,
                    color: colorFor(selected.kind),
                  }}
                >
                  {selected.kind.replace("_", " · ")}
                </span>
                <div style={{ flex: 1 }} />
                <button
                  onClick={() => setSelected(null)}
                  style={{
                    border: "none",
                    background: "transparent",
                    color: "#6b7280",
                    cursor: "pointer",
                    fontSize: 18,
                    lineHeight: 1,
                  }}
                  aria-label="Close panel"
                >
                  ×
                </button>
              </div>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 500,
                  color: "#111827",
                  marginBottom: 12,
                  whiteSpace: "pre-wrap",
                }}
              >
                {selected.label}
              </div>
              {selected.id.startsWith("entity:") && (
                <a
                  href={`/entity/${selected.id.slice("entity:".length)}`}
                  style={{
                    display: "inline-block",
                    padding: "6px 12px",
                    borderRadius: 8,
                    background: "#111827",
                    color: "white",
                    textDecoration: "none",
                    fontSize: 12,
                  }}
                >
                  Open entity →
                </a>
              )}
              {selected.id.startsWith("memory:") && (
                <a
                  href={`/explore`}
                  style={{
                    display: "inline-block",
                    padding: "6px 12px",
                    borderRadius: 8,
                    background: "#111827",
                    color: "white",
                    textDecoration: "none",
                    fontSize: 12,
                  }}
                >
                  Browse in Explore →
                </a>
              )}
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}

function Legend() {
  const items: Array<[string, string]> = [
    ["entity_person", "Person"],
    ["entity_place", "Place"],
    ["entity_event", "Event"],
    ["entity_topic", "Topic"],
    ["memory_card", "Memory card"],
    ["memory_chunk", "Memory chunk"],
  ];
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 12,
        fontSize: 12,
        color: "#374151",
      }}
    >
      {items.map(([k, label]) => (
        <div key={k} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: colorFor(k),
              display: "inline-block",
            }}
          />
          {label}
        </div>
      ))}
    </div>
  );
}
