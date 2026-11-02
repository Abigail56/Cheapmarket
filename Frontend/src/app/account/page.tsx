"use client";

import Link from "next/link";
import { useState } from "react";

import { CheckIcon } from "@/components/icons";
import { Alert, Field, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { localPhone } from "@/lib/format";
import type { User } from "@/lib/types";
import { useAuth } from "@/providers/auth";
import { useToast } from "@/providers/toast";
import { PasswordInput } from "@/components/password-input";

export default function ProfilePage() {
  const { user } = useAuth();
  if (!user) return null; // the layout redirects
  return (
    <div className="space-y-6">
      <ProfileForm user={user} />
      <PhoneVerification user={user} />
      <PasswordForm />
    </div>
  );
}

function ProfileForm({ user }: { user: User }) {
  const { setUser } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user.full_name);
  const [phone, setPhone] = useState(localPhone(user.phone));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const updated = await api<User>("/users/me", {
        method: "PATCH",
        body: { full_name: name.trim() || null, phone: phone.trim() || null },
      });
      setUser(updated);
      toast("Profile saved");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save your profile");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="card space-y-4 p-5" noValidate>
      <h2 className="text-lg font-bold">Profile</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name" htmlFor="p-name">
          <input id="p-name" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
        </Field>
        <Field label="Email" htmlFor="p-email" hint="Contact us to change your email">
          <input id="p-email" className="input" value={user.email} disabled />
        </Field>
        <Field label="Phone" htmlFor="p-phone" hint="Changing it means verifying the new number">
          <input
            id="p-phone"
            className="input"
            type="tel"
            inputMode="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="tel"
          />
        </Field>
      </div>
      {error && <Alert>{error}</Alert>}
      <button className="btn-primary" disabled={busy}>
        {busy && <Spinner className="h-4 w-4" />}
        Save changes
      </button>
    </form>
  );
}

function PhoneVerification({ user }: { user: User }) {
  const { setUser } = useAuth();
  const toast = useToast();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!user.phone) return null;

  if (user.phone_verified_at) {
    return (
      <div className="card flex items-center gap-3 p-5 text-sm">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-brand-100 text-brand-700">
          <CheckIcon width={16} height={16} />
        </span>
        <span>
          <strong>{localPhone(user.phone)}</strong> is verified. Order updates are texted here.
        </span>
      </div>
    );
  }

  async function send() {
    setBusy(true);
    setError("");
    try {
      await api("/users/me/phone/verify", { method: "POST" });
      setSent(true);
      toast("Code sent by SMS");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't send the code");
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setUser(await api<User>("/users/me/phone/verify/confirm", { method: "POST", body: { code: code.trim() } }));
      toast("Phone number verified");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That code didn't work");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card space-y-4 p-5">
      <div>
        <h2 className="text-lg font-bold">Verify your phone</h2>
        <p className="text-sm text-slate-600">
          Confirm <strong>{localPhone(user.phone)}</strong> so delivery updates and codes reach you.
        </p>
      </div>
      {sent ? (
        <form onSubmit={confirm} className="flex flex-wrap items-end gap-3" noValidate>
          <Field label="6-digit code" htmlFor="v-code">
            <input
              id="v-code"
              className="input w-40 tracking-[0.4em]"
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              autoComplete="one-time-code"
            />
          </Field>
          <button className="btn-primary" disabled={busy || code.length !== 6}>
            {busy && <Spinner className="h-4 w-4" />}
            Verify
          </button>
          <button type="button" className="btn-ghost" onClick={send} disabled={busy}>
            Resend
          </button>
        </form>
      ) : (
        <button type="button" className="btn-secondary" onClick={send} disabled={busy}>
          {busy && <Spinner className="h-4 w-4" />}
          Text me a code
        </button>
      )}
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

function PasswordForm() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next.length < 8) {
      setError("Your new password needs at least 8 characters.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/users/me/password", { method: "POST", body: { current_password: current, new_password: next } });
      setCurrent("");
      setNext("");
      toast("Password changed");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change your password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card space-y-4 p-5" noValidate>
      <h2 className="text-lg font-bold">Change password</h2>
      <p className="-mt-2 text-sm text-slate-600">
        Signed up with Google and never set a password? Use{" "}
        <Link href="/forgot-password" className="link">
          forgot password
        </Link>{" "}
        to create one.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Current password" htmlFor="pw-current">
          <PasswordInput
            id="pw-current"
            className="input"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
          />
        </Field>
        <Field label="New password" htmlFor="pw-new" hint="At least 8 characters">
          <PasswordInput
            id="pw-new"
            className="input"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
          />
        </Field>
      </div>
      {error && <Alert>{error}</Alert>}
      <button className="btn-secondary" disabled={busy || !current || !next}>
        {busy && <Spinner className="h-4 w-4" />}
        Update password
      </button>
    </form>
  );
}
