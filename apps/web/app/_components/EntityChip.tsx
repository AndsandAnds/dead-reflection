"use client";

import Link from "next/link";

import type { EntityKind, LinkedEntity } from "../_lib/memory";

const KIND_COLORS: Record<EntityKind, { bg: string; fg: string }> = {
  person: { bg: "rgba(236,72,153,0.12)", fg: "rgba(190,24,93,1)" },
  place: { bg: "rgba(34,197,94,0.12)", fg: "rgba(22,101,52,1)" },
  event: { bg: "rgba(245,158,11,0.14)", fg: "rgba(146,64,14,1)" },
  topic: { bg: "rgba(99,102,241,0.12)", fg: "rgba(67,56,202,1)" },
};

export function EntityChip({
  entity,
  onClick,
}: {
  entity: LinkedEntity;
  onClick?: () => void;
}) {
  const { bg, fg } = KIND_COLORS[entity.kind];
  const inner = (
    <>
      <span style={{ opacity: 0.6, fontSize: 10 }}>{entity.kind}</span>
      <span>{entity.name}</span>
    </>
  );
  const style: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "3px 8px",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 500,
    color: fg,
    background: bg,
    border: `1px solid ${fg}22`,
    textDecoration: "none",
    cursor: onClick ? "pointer" : "default",
  };
  if (onClick) {
    return (
      <button onClick={onClick} style={{ ...style, border: "none" }}>
        {inner}
      </button>
    );
  }
  return (
    <Link href={`/entity/${entity.id}`} style={style}>
      {inner}
    </Link>
  );
}
