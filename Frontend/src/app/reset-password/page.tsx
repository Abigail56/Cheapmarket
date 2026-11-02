"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthShell } from "@/components/auth-shell";
import { Alert, Field, PageLoading, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useToast } from "@/providers/toast";
import { PasswordInput } from "@/components/password-input";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <ResetForm />
    </Suspense>
  );
}

function ResetForm() {
  const router = useRouter();
  const toast = useToast();
  const [email, setEmail] = useState(useSearchParams().get("email") ?? "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !/^\d{6}$/.test(code.trim()) || password.length < 8) {
      setError("Enter your email, the 6-digit code and a new password of at least 8 characters.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/auth/password/reset", {
        method: "POST",
        body: { email: email.trim(), code: code.trim(), new_password: password },
        auth: false,
      });
      toast("Password changed. Please sign in with your new password.");
      router.replace("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't reset your password");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Set a new password"
      subtitle="If the email belongs to an account, a code is on its way. It works for 15 minutes."
      footer={
        <Link href="/forgot-password" className="link">
          Didn&apos;t get a code? Send another
        </Link>
      }
    >
      <form className="space-y-4" onSubmit={submit} noValidate>
        <Field label="Email" htmlFor="email">
          <input id="email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </Field>
        <Field label="6-digit code" htmlFor="code">
          <input
            id="code"
            className="input tracking-[0.4em]"
            inputMode="numeric"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            autoComplete="one-time-code"
          />
        </Field>
        <Field label="New password" htmlFor="password" hint="At least 8 characters. You'll be signed out on other devices.">
          <PasswordInput
            id="password"
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <button className="btn-primary w-full py-3" disabled={busy}>
          {busy && <Spinner className="h-4 w-4" />}
          Change password
        </button>
      </form>
    </AuthShell>
  );
}
