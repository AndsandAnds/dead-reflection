"use client";

import { useState } from "react";

export function SearchBar({
  initial = "",
  placeholder = "Search your memories...",
  onSearch,
  busy = false,
}: {
  initial?: string;
  placeholder?: string;
  onSearch: (query: string) => void;
  busy?: boolean;
}) {
  const [value, setValue] = useState(initial);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onSearch(value.trim());
      }}
      style={{ display: "flex", gap: 8, width: "100%" }}
    >
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        style={{
          flex: 1,
          padding: "10px 14px",
          borderRadius: 10,
          border: "1px solid rgba(0,0,0,0.12)",
          fontSize: 14,
          background: "white",
        }}
      />
      <button
        type="submit"
        disabled={busy || !value.trim()}
        style={{
          padding: "10px 18px",
          borderRadius: 10,
          border: "none",
          background:
            "linear-gradient(135deg, rgba(99,102,241,1), rgba(236,72,153,1))",
          color: "white",
          fontWeight: 600,
          cursor: busy ? "wait" : "pointer",
          opacity: busy ? 0.7 : 1,
        }}
      >
        {busy ? "Searching..." : "Search"}
      </button>
    </form>
  );
}
