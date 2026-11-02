// Small shared UI pieces used across pages
import Link from "next/link";

import type { OrderStatus, PaymentStatus } from "@/lib/types";
import { PAYMENT_STATUS_LABEL, STATUS_LABEL } from "@/lib/format";

import { SITE_NAME } from "@/lib/config";

import { LeafIcon } from "./icons";

export function Logo({ className = "", light = false }: { className?: string; light?: boolean }) {
  return (
    <Link href="/" className={`block shrink-0 ${className}`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={light ? "/images/logo-light.png" : "/images/logo.png"}
        alt={`${SITE_NAME} home`}
        width={662}
        height={144}
        className="h-9 w-auto sm:h-12"
      />
    </Link>
  );
}

export function Spinner({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block animate-spin rounded-full border-2 border-current border-r-transparent ${className}`}
    />
  );
}

export function PageLoading() {
  return (
    <div className="grid min-h-[40vh] place-items-center text-brand-600">
      <Spinner className="h-8 w-8" />
    </div>
  );
}

export function Alert({
  tone = "error",
  children,
}: {
  tone?: "error" | "success" | "info" | "warning";
  children: React.ReactNode;
}) {
  const styles = {
    error: "border-red-200 bg-red-50 text-red-800",
    success: "border-brand-200 bg-brand-50 text-brand-800",
    info: "border-sky-200 bg-sky-50 text-sky-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-xl border px-4 py-3 text-sm ${styles}`}>
      {children}
    </div>
  );
}

export function Field({
  label,
  error,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  error?: string;
  hint?: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="label">
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-red-600">{error}</p>
      ) : hint ? (
        <p className="mt-1 text-xs text-slate-500">{hint}</p>
      ) : null}
    </div>
  );
}

export function StatusBadge({ status }: { status: OrderStatus }) {
  const tone: Record<OrderStatus, string> = {
    pending: "bg-amber-100 text-amber-800",
    confirmed: "bg-sky-100 text-sky-800",
    packed: "bg-indigo-100 text-indigo-800",
    out_for_delivery: "bg-deal-100 text-deal-700",
    delivered: "bg-brand-100 text-brand-800",
    cancelled: "bg-slate-200 text-slate-700",
  };
  return (
    <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${tone[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

export function PaymentBadge({ status }: { status: PaymentStatus }) {
  const tone: Record<PaymentStatus, string> = {
    unpaid: "bg-slate-100 text-slate-700",
    paid: "bg-brand-100 text-brand-800",
    failed: "bg-red-100 text-red-700",
    refunded: "bg-slate-100 text-slate-700",
  };
  return (
    <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${tone[status]}`}>
      {PAYMENT_STATUS_LABEL[status]}
    </span>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center gap-3 px-6 py-14 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-full bg-brand-50 text-brand-600">
        <LeafIcon width={28} height={28} />
      </span>
      <h2 className="text-lg font-bold text-slate-900">{title}</h2>
      {children && <div className="max-w-md text-sm text-slate-600">{children}</div>}
      {action}
    </div>
  );
}
