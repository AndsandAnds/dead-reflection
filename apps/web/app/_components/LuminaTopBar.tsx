"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import type { AuthUser } from "../_lib/auth";
import { authLogout } from "../_lib/auth";

export function LuminaTopBar({ user }: { user: AuthUser }) {
  const router = useRouter();

  async function doLogout() {
    try {
      await authLogout();
    } finally {
      router.replace("/login");
    }
  }

  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        backdropFilter: "blur(10px)",
        background: "rgba(255,255,255,0.7)",
        borderBottom: "1px solid rgba(0,0,0,0.06)",
      }}
    >
      <div
        style={{
          maxWidth: 980,
          margin: "0 auto",
          padding: "14px 18px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Link
            href="/voice"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              textDecoration: "none",
              color: "#111827",
              fontWeight: 800,
              letterSpacing: -0.4,
              fontSize: 18,
            }}
          >
            <span
              style={{
                width: 14,
                height: 14,
                borderRadius: 5,
                background:
                  "linear-gradient(135deg, rgba(99,102,241,1), rgba(236,72,153,1))",
                boxShadow: "0 8px 20px rgba(0,0,0,0.18)",
              }}
            />
            Lumina
          </Link>

          <nav style={{ display: "flex", gap: 10, fontSize: 14 }}>
            <Link href="/voice" style={{ color: "#374151" }}>
              Voice
            </Link>
            <Link href="/avatar" style={{ color: "#374151" }}>
              Avatar
            </Link>
            <Link href="/memory" style={{ color: "#374151" }}>
              Memory
            </Link>
          </nav>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ fontSize: 13, color: "#6b7280" }}>{user.name}</div>
          <button
            onClick={() => void doLogout()}
            style={{
              border: "1px solid rgba(0,0,0,0.12)",
              background: "white",
              padding: "8px 10px",
              borderRadius: 10,
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            Logout
          </button>
        </div>
      </div>
    </header>
  );
}
