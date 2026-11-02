"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

interface GoogleId {
  accounts: {
    id: {
      initialize: (o: { client_id: string; callback: (r: { credential: string }) => void }) => void;
      renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
    };
  };
}
declare global {
  interface Window {
    google?: GoogleId;
  }
}

let script: Promise<void> | null = null;
function loadScript(): Promise<void> {
  script ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      script = null;
      reject(new Error("Google sign-in couldn't load"));
    };
    document.head.appendChild(s);
  });
  return script;
}

// "Continue with Google". Renders nothing unless the API has GOOGLE_CLIENT_ID set.
export function GoogleButton({ onCredential }: { onCredential: (idToken: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [clientId, setClientId] = useState<string | null>(null);
  const callback = useRef(onCredential);
  useEffect(() => {
    callback.current = onCredential;
  }, [onCredential]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cfg = await api<{ google_client_id: string | null }>("/auth/config", { auth: false }).catch(() => null);
      if (!cfg?.google_client_id || cancelled) return;
      await loadScript();
      if (!cancelled && window.google) setClientId(cfg.google_client_id);
    })().catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Runs once the wrapper is visible: a hidden element measures 0 wide, and Google's button
  // takes a fixed pixel width (400 at most), so it wouldn't fit the card otherwise.
  useEffect(() => {
    if (!clientId || !ref.current || !window.google) return;
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: (r) => callback.current(r.credential),
    });
    window.google.accounts.id.renderButton(ref.current, {
      theme: "outline",
      size: "large",
      shape: "rectangular",
      text: "continue_with",
      width: Math.min(ref.current.offsetWidth || 320, 400),
    });
  }, [clientId]);

  return (
    <div className={clientId ? "space-y-4" : "hidden"}>
      <div ref={ref} className="flex min-h-11 w-full justify-center" />
      <div className="flex items-center gap-3 text-xs text-slate-400">
        <span className="h-px flex-1 bg-slate-200" /> or <span className="h-px flex-1 bg-slate-200" />
      </div>
    </div>
  );
}
