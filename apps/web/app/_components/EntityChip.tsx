"use client";

import Link from "next/link";

import type { EntityKind, LinkedEntity } from "../_lib/memory";

// Palette kept in sync with graph/page.tsx COLOR_BY_KIND. If you tweak one,
// tweak the other. fg is the saturated solid; bg is a low-alpha wash for
// the chip background.
const KIND_COLORS: Record<EntityKind, { bg: string; fg: string }> = {
  // Hot pink
  person: { bg: "rgba(236,72,153,0.12)", fg: "rgba(190,24,93,1)" },
  // Teal
  place: { bg: "rgba(20,184,166,0.14)", fg: "rgba(15,118,110,1)" },
  // Orange
  event: { bg: "rgba(249,115,22,0.14)", fg: "rgba(194,65,12,1)" },
  // Marigold (warm yellow-orange)
  topic: { bg: "rgba(234,179,8,0.16)", fg: "rgba(161,98,7,1)" },
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
