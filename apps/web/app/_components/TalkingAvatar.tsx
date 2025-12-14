"use client";

export function TalkingAvatar(props: {
  name: string;
  imageUrl?: string | null;
  level: number; // 0..1
  size?: number;
}) {
  const size = props.size ?? 220;
  const level = Number.isFinite(props.level)
    ? Math.max(0, Math.min(1, props.level))
    : 0;
  const speaking = level > 0.02;
  const pulse = speaking ? 1 + Math.min(0.06, level * 0.08) : 1;
  const glow = speaking ? Math.min(0.55, level * 0.85) : 0.0;
  const initials = props.name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");

  return (
    <div style={{ display: "grid", justifyItems: "center", gap: 10 }}>
      <div
        style={{
          width: size,
          height: size,
          borderRadius: 24,
          overflow: "hidden",
          border: "1px solid rgba(0,0,0,0.10)",
          background:
            "linear-gradient(135deg, rgba(99,102,241,0.18), rgba(236,72,153,0.14))",
          boxShadow: `0 18px 50px rgba(0,0,0,0.16), 0 0 0 6px rgba(99,102,241,${
            glow * 0.35
          })`,
          transform: `scale(${pulse})`,
          transition: "transform 60ms linear, box-shadow 120ms linear",
          position: "relative",
        }}
        aria-label="avatar"
      >
        {props.imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={props.imageUrl}
            alt={props.name}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "grid",
              placeItems: "center",
              fontWeight: 900,
              letterSpacing: -0.8,
              fontSize: 44,
              color: "rgba(17,24,39,0.72)",
            }}
          >
            {initials || "L"}
          </div>
        )}

        {/* “mouth” indicator (cheap but effective) */}
        <div
          style={{
            position: "absolute",
            left: "50%",
            bottom: 18,
            transform: "translateX(-50%)",
            width: Math.round(68 + level * 46),
            height: Math.round(10 + level * 18),
            borderRadius: 999,
            background: `rgba(17,24,39,${0.1 + glow * 0.35})`,
            boxShadow: speaking ? "0 8px 22px rgba(0,0,0,0.18)" : "none",
            transition:
              "width 50ms linear, height 50ms linear, background 90ms linear",
            backdropFilter: "blur(8px)",
          }}
        />
      </div>
      <div style={{ fontSize: 13, color: "#6b7280" }}>{props.name}</div>
    </div>
  );
}
