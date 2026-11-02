"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { OrderView } from "@/components/order-view";
import { PhoneGate } from "@/components/phone-gate";
import { Alert, EmptyState, PageLoading } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { orderAccessStore, type OrderAccess } from "@/lib/storage";
import type { Order } from "@/lib/types";
import { useAuth } from "@/providers/auth";


export default function OrderPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <OrderLoader />
    </Suspense>
  );
}

function OrderLoader() {
  const { number } = useParams<{ number: string }>();
  const search = useSearchParams();
  const { user, ready } = useAuth();
  const [order, setOrder] = useState<Order | null>(null);
  const [access, setAccess] = useState<OrderAccess | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "needs-phone" | "missing" | "error">("loading");

  const load = useCallback(async () => {
    const saved = orderAccessStore.get(number);
    setAccess(saved);
    try {
      if (user) {
        try {
          setOrder(await api<Order>(`/orders/${encodeURIComponent(number)}`));
          setState("ok");
          return;
        } catch (e) {
          // Not this account's order (e.g. placed as a guest): fall back to the phone check
          if (!(e instanceof ApiError && e.status === 404)) throw e;
        }
      }
      if (saved?.phone) {
        setOrder(await api<Order>("/orders/track", { method: "POST", body: { order_number: number, phone: saved.phone } }));
        setState("ok");
        return;
      }
      setState("needs-phone");
    } catch (e) {
      setState(e instanceof ApiError && e.status === 404 ? "missing" : "error");
    }
  }, [number, user]);

  useEffect(() => {
    if (ready) void load(); // eslint-disable-line react-hooks/set-state-in-effect -- fetch on mount
  }, [ready, load]);

  if (state === "loading") return <PageLoading />;

  return (
    <div className="container-page max-w-5xl py-8">
      {search.get("placed") && state === "ok" && order && (
        <div className="mb-6">
          <Alert tone="success">
            <strong>Thank you, {order.customer_name.split(" ")[0]}!</strong> Your order is in. We&apos;ve texted you
            the details{order.customer_email ? " and sent a copy by email" : ""}.
            {search.get("pay") === "retry" && " The payment page didn't open: use “Pay now” below to try again."}
          </Alert>
        </div>
      )}

      {state === "ok" && order && (
        <OrderView order={order} phone={access?.phone} instructions={access?.instructions} onChange={setOrder} />
      )}

      {state === "needs-phone" && (
        <PhoneGate
          orderNumber={number}
          onFound={(o, phone) => {
            orderAccessStore.set(o.order_number, { phone });
            setAccess(orderAccessStore.get(o.order_number));
            setOrder(o);
            setState("ok");
          }}
        />
      )}

      {state === "missing" && (
        <EmptyState
          title="We couldn't find that order"
          action={
            <Link href="/track" className="btn-primary">
              Look up an order
            </Link>
          }
        >
          Check the order number. If you ordered as a guest, look it up with the phone number you used.
        </EmptyState>
      )}

      {state === "error" && (
        <EmptyState
          title="Couldn't load your order"
          action={
            <button type="button" className="btn-primary" onClick={() => void load()}>
              Try again
            </button>
          }
        >
          Please check your connection.
        </EmptyState>
      )}

      <p className="mt-8 text-center text-sm">
        <Link href="/shop" className="link">
          Continue shopping
        </Link>
      </p>
    </div>
  );
}
