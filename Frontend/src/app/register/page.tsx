"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthShell, safeNext } from "@/components/auth-shell";
import { GoogleButton } from "@/components/google-button";
import { Alert, Field, PageLoading, Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/providers/auth";
import { PasswordInput } from "@/components/password-input";

export default function RegisterPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <RegisterForm />
    </Suspense>
  );
}

function RegisterForm() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const { register, googleSignIn } = useAuth();
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", password: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      router.replace(next);
    } catch (e) {
      if (e instanceof ApiError) setErrors(e.fields);
      setError(e instanceof Error ? e.message : "Couldn't create your account");
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const v: Record<string, string> = {};
    if (form.full_name.trim().length < 2) v.full_name = "Enter your full name";
    if (!/^\S+@\S+\.\S+$/.test(form.email.trim())) v.email = "Enter a valid email";
    if (form.password.length < 8) v.password = "Use at least 8 characters";
    setErrors(v);
    if (Object.keys(v).length) return;
    void run(() =>
      register({
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim() || undefined,
        password: form.password,
      }),
    );
  }

  return (
    <AuthShell
      title="Create an account"
      subtitle="Save your delivery addresses and view your order history."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="link">
            Sign in
          </Link>
        </>
      }
    >
      <GoogleButton onCredential={(token) => run(() => googleSignIn(token))} />
      <form className="space-y-4" onSubmit={submit} noValidate>
        <Field label="Full name" htmlFor="full_name" error={errors.full_name}>
          <input id="full_name" className="input" value={form.full_name} onChange={set("full_name")} autoComplete="name" />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email}>
          <input id="email" type="email" className="input" value={form.email} onChange={set("email")} autoComplete="email" />
        </Field>
        <Field label="Phone (optional)" htmlFor="phone" error={errors.phone} hint="For order updates by SMS">
          <input
            id="phone"
            type="tel"
            inputMode="tel"
            className="input"
            placeholder="0803 123 4567"
            value={form.phone}
            onChange={set("phone")}
            autoComplete="tel"
          />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password} hint="At least 8 characters">
          <PasswordInput
            id="password"
            className="input"
            value={form.password}
            onChange={set("password")}
            autoComplete="new-password"
          />
        </Field>
        {error && !Object.keys(errors).length && <Alert>{error}</Alert>}
        <button className="btn-primary w-full py-3" disabled={busy}>
          {busy && <Spinner className="h-4 w-4" />}
          Create account
        </button>
      </form>
    </AuthShell>
  );
}
