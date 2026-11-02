// NEXT_PUBLIC_* values are inlined into the browser bundle at build time
const CONFIGURED_API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const PRIVATE_HOST = /^(127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)$/;

// In local development the API is on this same computer, but "localhost" on a phone means the
// phone. When the shop was opened by IP, reach the API at that same IP.
function browserApiUrl(): string {
  if (typeof window === "undefined" || !PRIVATE_HOST.test(window.location.hostname)) return CONFIGURED_API_URL;
  const url = new URL(CONFIGURED_API_URL);
  if (url.hostname !== "localhost") return CONFIGURED_API_URL;
  url.hostname = window.location.hostname;
  return url.origin;
}

export const API_URL = browserApiUrl();

// The Next.js server may reach the API on a private address (e.g. inside Docker)
export const SERVER_API_URL = (process.env.API_INTERNAL_URL || API_URL).replace(/\/$/, "");

export const PAYMENT_PROVIDER: "paystack" | "flutterwave" =
  process.env.NEXT_PUBLIC_PAYMENT_PROVIDER === "flutterwave" ? "flutterwave" : "paystack";

export const SUPPORT_PHONE = process.env.NEXT_PUBLIC_SUPPORT_PHONE || "";
export const SUPPORT_EMAIL = process.env.NEXT_PUBLIC_SUPPORT_EMAIL || "";

export const SITE_NAME = "Cheapmarket";
export const SITE_TAGLINE = "Groceries and household items delivered to your door";
