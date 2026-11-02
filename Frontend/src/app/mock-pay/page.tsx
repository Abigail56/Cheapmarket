"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Alert, PageLoading, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Order } from "@/lib/types";

// Development only: the API sends card payments here when it has no gateway keys
// (ENVIRONMENT=local). In production the API never links to this page, and the
// simulate endpoint it calls answers 404.
export default function MockPayPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <MockPay />
    </Suspense>
  );
}

function MockPay() {
  const router = useRouter();
  const reference = useSearchParams().get("reference") || "";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function succeed() {
    setBusy(true);
    setError("");
    try {
      const order = await api<Order>(`/payments/dev/simulate-success/${encodeURIComponent(reference)}`, {
        method: "POST",
        auth: false,
      });
      router.push(`/orders/${order.order_number}/payment-complete?reference=${encodeURIComponent(reference)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't simulate the payment");
      setBusy(false);
    }
  }

  return (
    <div className="container-page max-w-md py-14">
      <div className="card space-y-4 p-8">
        <p className="inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-800">
          TEST MODE
        </p>
        <h1 className="text-xl font-extrabold">Pretend payment</h1>
        <p className="text-sm text-slate-600">
          The API has no Paystack/Flutterwave keys, so no real payment page exists. Use this to test the flow.
        </p>
        <p className="font-mono text-xs text-slate-500">Reference: {reference || "missing"}</p>
        {error && <Alert>{error}</Alert>}
        <button type="button" className="btn-primary w-full py-3" onClick={succeed} disabled={busy || !reference}>
          {busy && <Spinner className="h-4 w-4" />}
          Simulate successful payment
        </button>
        <button type="button" className="btn-secondary w-full" onClick={() => router.back()}>
          Go back without paying
        </button>
      </div>
    </div>
  );
}
