"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthShell } from "@/components/auth-shell";
import { Alert, Field, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError("Enter the email on your account.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      // Answers the same whether or not the account exists
      await api("/auth/password/forgot", { method: "POST", body: { email: email.trim() }, auth: false });
      router.push(`/reset-password?email=${encodeURIComponent(email.trim())}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't send the code");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Forgot your password?"
      subtitle="We'll email you a 6-digit code to set a new one."
      footer={
        <Link href="/login" className="link">
          Back to sign in
        </Link>
      }
    >
      <form className="space-y-4" onSubmit={submit} noValidate>
        <Field label="Email" htmlFor="email">
          <input id="email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </Field>
        {error && <Alert>{error}</Alert>}
        <button className="btn-primary w-full py-3" disabled={busy}>
          {busy && <Spinner className="h-4 w-4" />}
          Send code
        </button>
      </form>
    </AuthShell>
  );
}
