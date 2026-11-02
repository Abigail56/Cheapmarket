// Browser-side API client: adds the login token and guest cart session, refreshes an
// expired token once, and turns every error into an ApiError with a readable message.
import { API_URL } from "./config";
import { cartSessionStore, tokenStore } from "./storage";
import type { TokenPair } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

type Json = Record<string, unknown> | unknown[];

interface Options {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: Json;
  auth?: boolean; // send the login token if there is one (default true)
  cart?: boolean; // send the guest cart session (default false)
}

// Called when the session can't be refreshed, so the UI can show "signed out"
let onSignedOut: (() => void) | null = null;
export function setSignedOutHandler(fn: (() => void) | null) {
  onSignedOut = fn;
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  // One refresh at a time: refresh tokens rotate, so parallel refreshes would race
  refreshing ??= (async () => {
    const tokens = tokenStore.get();
    if (!tokens) return false;
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh }),
      });
      if (!res.ok) {
        tokenStore.set(null);
        onSignedOut?.();
        return false;
      }
      const pair = (await res.json()) as TokenPair;
      tokenStore.set({ access: pair.access_token, refresh: pair.refresh_token });
      return true;
    } catch {
      return false; // offline: keep the tokens and let the caller see the network error
    }
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

const FIELD_NAMES: Record<string, string> = {
  customer_phone: "phone",
  customer_name: "name",
  customer_email: "email",
};

async function toError(res: Response): Promise<ApiError> {
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* not JSON */
  }
  const err = (data as { error?: { code?: string; message?: string } })?.error;
  if (err?.message) return new ApiError(err.message, res.status, err.code || "error");

  // FastAPI validation errors: {"detail": [{loc, msg}, ...]}
  const detail = (data as { detail?: unknown })?.detail;
  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const d of detail as { loc?: (string | number)[]; msg?: string }[]) {
      const field = String(d.loc?.[d.loc.length - 1] ?? "");
      const msg = (d.msg || "Invalid value").replace(/^Value error, /, "");
      if (field && field !== "body") fields[FIELD_NAMES[field] || field] = msg;
      else fields._ = msg;
    }
    const first = Object.values(fields)[0] || "Please check the form";
    return new ApiError(first, res.status, "validation_error", fields);
  }
  if (typeof detail === "string") return new ApiError(detail, res.status, "error");
  if (res.status === 429) return new ApiError("Too many attempts. Please wait a minute.", 429, "rate_limited");
  return new ApiError("Something went wrong. Please try again.", res.status, "error");
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const { method = "GET", body, auth = true, cart = false } = opts;

  const send = () => {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const tokens = auth ? tokenStore.get() : null;
    if (tokens) headers.Authorization = `Bearer ${tokens.access}`;
    const session = cart ? cartSessionStore.get() : null;
    if (session) headers["X-Cart-Session"] = session;
    return fetch(`${API_URL}/api/v1${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  };

  let res: Response;
  try {
    res = await send();
    if (res.status === 401 && auth && tokenStore.get() && (await refreshTokens())) {
      res = await send();
    }
  } catch {
    throw new ApiError("Can't reach the shop right now. Check your internet connection.", 0, "network");
  }
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
