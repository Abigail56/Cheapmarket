"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthShell, safeNext } from "@/components/auth-shell";
import { GoogleButton } from "@/components/google-button";
import { Alert, Field, PageLoading, Spinner } from "@/components/ui";
import { useAuth } from "@/providers/auth";
import { PasswordInput } from "@/components/password-input";

export default function LoginPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const next = safeNext(search.get("next"));
  const { login, googleSignIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      router.replace(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't sign you in");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Sign in"
      subtitle="Use your account to check out and view your orders."
      footer={
        <>
          New here?{" "}
          <Link href={`/register${next !== "/account" ? `?next=${encodeURIComponent(next)}` : ""}`} className="link">
            Create an account
          </Link>
        </>
      }
    >
      <GoogleButton onCredential={(token) => run(() => googleSignIn(token))} />
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!email || !password) {
            setError("Enter your email and password.");
            return;
          }
          void run(() => login(email.trim(), password));
        }}
        noValidate
      >
        <Field label="Email" htmlFor="email">
          <input
            id="email"
            type="email"
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </Field>
        <Field label="Password" htmlFor="password">
          <PasswordInput
            id="password"
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </Field>
        <div className="text-right text-sm">
          <Link href="/forgot-password" className="link">
            Forgot password?
          </Link>
        </div>
        {error && <Alert>{error}</Alert>}
        <button className="btn-primary w-full py-3" disabled={busy}>
          {busy && <Spinner className="h-4 w-4" />}
          Sign in
        </button>
      </form>
    </AuthShell>
  );
}
