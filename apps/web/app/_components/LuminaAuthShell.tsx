"use client";

import Link from "next/link";

export function LuminaAuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: any;
}) {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        background:
          "radial-gradient(1200px 600px at 20% 0%, rgba(99,102,241,0.25), transparent), radial-gradient(900px 600px at 90% 20%, rgba(236,72,153,0.18), transparent), #0b1020",
        color: "#e6e9f5",
      }}
    >
      <section style={{ width: "100%", maxWidth: 520 }}>
        <div style={{ marginBottom: 18 }}>
          <Link
            href="/voice"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              textDecoration: "none",
              color: "inherit",
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 12,
                background:
                  "linear-gradient(135deg, rgba(99,102,241,1), rgba(236,72,153,1))",
                boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
              }}
            />
            <div>
              <div style={{ fontSize: 14, opacity: 0.8 }}>Lumina</div>
              <div style={{ fontSize: 12, opacity: 0.6 }}>
                Voice-first local assistant
              </div>
            </div>
          </Link>
        </div>

        <div
          style={{
            borderRadius: 18,
            border: "1px solid rgba(255,255,255,0.08)",
            background: "rgba(255,255,255,0.06)",
            boxShadow: "0 20px 70px rgba(0,0,0,0.45)",
            padding: 22,
            backdropFilter: "blur(10px)",
          }}
        >
          <h1 style={{ margin: 0, fontSize: 28, letterSpacing: -0.5 }}>
            {title}
          </h1>
          {subtitle ? (
            <p style={{ margin: "8px 0 0 0", opacity: 0.75 }}>{subtitle}</p>
          ) : null}

          <div style={{ marginTop: 18 }}>{children}</div>
        </div>
      </section>
    </main>
  );
}

export function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  autoComplete?: string;
}) {
  return (
    <label style={{ display: "grid", gap: 6 }}>
      <span style={{ fontSize: 12, opacity: 0.8 }}>{label}</span>
      <input
        value={value}
        onChange={(e: any) => onChange(e.target.value)}
        type={type}
        placeholder={placeholder}
        autoComplete={autoComplete}
        style={{
          width: "100%",
          padding: "12px 12px",
          borderRadius: 12,
          border: "1px solid rgba(255,255,255,0.12)",
          background: "rgba(0,0,0,0.25)",
          color: "white",
          outline: "none",
        }}
      />
    </label>
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
}: {
  children?: any;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        width: "100%",
        border: 0,
        padding: "12px 14px",
        borderRadius: 12,
        cursor: disabled ? "not-allowed" : "pointer",
        color: "white",
        fontWeight: 600,
        background: disabled
          ? "rgba(255,255,255,0.12)"
          : "linear-gradient(135deg, rgba(99,102,241,1), rgba(236,72,153,1))",
        boxShadow: disabled ? "none" : "0 14px 40px rgba(0,0,0,0.35)",
      }}
    >
      {children}
    </button>
  );
}
