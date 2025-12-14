"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Field,
  LuminaAuthShell,
  PrimaryButton,
} from "../_components/LuminaAuthShell";
import { authLogin, authMe } from "../_lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    // If already logged in, skip login screen.
    (async () => {
      const me = await authMe();
      if (me) router.replace("/voice");
    })();
  }, [router]);

  async function submit() {
    setStatus("loading");
    setError("");
    try {
      await authLogin({ email, password });
      router.push("/voice");
    } catch (e: any) {
      setError(String(e?.message ?? "login_failed"));
      setStatus("error");
    }
  }

  return (
    <LuminaAuthShell title="Welcome back" subtitle="Sign in to Lumina">
      <div style={{ display: "grid", gap: 12 }}>
        <Field
          label="Email"
          value={email}
          onChange={setEmail}
          placeholder="you@domain.com"
          autoComplete="email"
        />
        <Field
          label="Password"
          value={password}
          onChange={setPassword}
          type="password"
          placeholder="••••••••"
          autoComplete="current-password"
        />

        {error ? (
          <div style={{ color: "#fecaca", fontSize: 13 }}>
            {error.includes("401") ? "Invalid email or password." : error}
          </div>
        ) : null}

        <PrimaryButton
          disabled={status === "loading" || !email || !password}
          onClick={() => void submit()}
        >
          {status === "loading" ? "Signing in…" : "Sign in"}
        </PrimaryButton>

        <div style={{ fontSize: 13, opacity: 0.75 }}>
          New here?{" "}
          <Link href="/signup" style={{ color: "white" }}>
            Create an account
          </Link>
        </div>
      </div>
    </LuminaAuthShell>
  );
}
