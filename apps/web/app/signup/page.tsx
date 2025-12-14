"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Field,
  LuminaAuthShell,
  PrimaryButton,
} from "../_components/LuminaAuthShell";
import { authMe, authSignup } from "../_lib/auth";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      const me = await authMe();
      if (me) router.replace("/voice");
    })();
  }, [router]);

  async function submit() {
    setStatus("loading");
    setError("");
    try {
      await authSignup({ name, email, password });
      router.push("/voice");
    } catch (e: any) {
      setError(String(e?.message ?? "signup_failed"));
      setStatus("error");
    }
  }

  return (
    <LuminaAuthShell
      title="Create your account"
      subtitle="Start a session with Lumina"
    >
      <div style={{ display: "grid", gap: 12 }}>
        <Field
          label="Name"
          value={name}
          onChange={setName}
          placeholder="Once"
          autoComplete="name"
        />
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
          placeholder="At least 8 characters"
          autoComplete="new-password"
        />

        {error ? (
          <div style={{ color: "#fecaca", fontSize: 13 }}>{error}</div>
        ) : null}

        <PrimaryButton
          disabled={
            status === "loading" || !name || !email || password.length < 8
          }
          onClick={() => void submit()}
        >
          {status === "loading" ? "Creating…" : "Create account"}
        </PrimaryButton>

        <div style={{ fontSize: 13, opacity: 0.75 }}>
          Already have an account?{" "}
          <Link href="/login" style={{ color: "white" }}>
            Sign in
          </Link>
        </div>
      </div>
    </LuminaAuthShell>
  );
}
