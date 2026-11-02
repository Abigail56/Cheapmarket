"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { CheckIcon } from "@/components/icons";
import { Alert, PageLoading, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type { Order } from "@/lib/types";

export default function PaymentCompletePage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <PaymentResult />
    </Suspense>
  );
}

// The gateway sends the customer back here. Paystack adds ?reference=, Flutterwave ?tx_ref=.
// The webhook usually confirms first; we also ask the API to verify, and retry a few times.
function PaymentResult() {
  const { number } = useParams<{ number: string }>();
  const search = useSearchParams();
  const reference = search.get("reference") || search.get("trxref") || search.get("tx_ref") || "";
  const cancelled = search.get("status") === "cancelled";

  const [order, setOrder] = useState<Order | null>(null);
  const [state, setState] = useState<"checking" | "paid" | "pending" | "error">("checking");

  useEffect(() => {
    if (!reference) return;
    let stop = false;
    (async () => {
      for (let attempt = 0; attempt < 5 && !stop; attempt++) {
        try {
          const o = await api<Order>(`/payments/verify/${encodeURIComponent(reference)}`, { auth: false });
          if (stop) return;
          setOrder(o);
          if (o.payment_status === "paid") {
            setState("paid");
            return;
          }
        } catch {
          if (attempt === 4 && !stop) setState("error");
        }
        await new Promise((r) => setTimeout(r, 2500));
      }
      if (!stop) setState((s) => (s === "checking" ? "pending" : s));
    })();
    return () => {
      stop = true;
    };
  }, [reference]);

  const orderLink = `/orders/${number}`;

  return (
    <div className="container-page max-w-lg py-14">
      <div className="card space-y-5 p-8 text-center">
        {!reference || cancelled ? (
          <>
            <h1 className="text-xl font-extrabold">Payment not completed</h1>
            <p className="text-sm text-slate-600">
              Your order is saved. You can pay any time from the order page.
            </p>
          </>
        ) : state === "checking" ? (
          <>
            <Spinner className="mx-auto h-10 w-10 text-brand-600" />
            <h1 className="text-xl font-extrabold">Confirming your payment…</h1>
            <p className="text-sm text-slate-600">This takes a few seconds. Please don&apos;t close this page.</p>
          </>
        ) : state === "paid" ? (
          <>
            <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-brand-100 text-brand-700">
              <CheckIcon width={30} height={30} />
            </span>
            <h1 className="text-xl font-extrabold">Payment received</h1>
            <p className="text-sm text-slate-600">
              {order ? `${money(order.total)} paid for order ${order.order_number}.` : "Thank you!"} We&apos;re
              getting it ready and will text you when it&apos;s on the way.
            </p>
          </>
        ) : state === "pending" ? (
          <>
            <h1 className="text-xl font-extrabold">Payment still processing</h1>
            <Alert tone="info">
              We haven&apos;t received confirmation from the bank yet. If you were charged, your order will update
              automatically within a few minutes. There&apos;s no need to pay again.
            </Alert>
          </>
        ) : (
          <>
            <h1 className="text-xl font-extrabold">We couldn&apos;t confirm the payment</h1>
            <p className="text-sm text-slate-600">
              If you were charged, your order will update automatically. Otherwise you can try again from the order
              page.
            </p>
          </>
        )}
        <Link href={orderLink} className="btn-primary w-full py-3">
          View order
        </Link>
      </div>
    </div>
  );
}
