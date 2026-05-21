"use client";

export function DateRangePicker({
  from,
  to,
  onChange,
}: {
  from: string | null; // YYYY-MM-DD
  to: string | null;
  onChange: (from: string | null, to: string | null) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
      <span style={{ color: "#6b7280" }}>From</span>
      <input
        type="date"
        value={from ?? ""}
        onChange={(e) => onChange(e.target.value || null, to)}
        style={dateInput}
      />
      <span style={{ color: "#6b7280" }}>to</span>
      <input
        type="date"
        value={to ?? ""}
        onChange={(e) => onChange(from, e.target.value || null)}
        style={dateInput}
      />
      {(from || to) && (
        <button
          onClick={() => onChange(null, null)}
          style={{
            padding: "4px 8px",
            borderRadius: 6,
            border: "1px solid rgba(0,0,0,0.12)",
            background: "white",
            fontSize: 11,
            cursor: "pointer",
          }}
          type="button"
        >
          clear
        </button>
      )}
    </div>
  );
}

const dateInput: React.CSSProperties = {
  padding: "6px 8px",
  borderRadius: 6,
  border: "1px solid rgba(0,0,0,0.12)",
  background: "white",
  fontSize: 12,
  fontFamily: "inherit",
};
