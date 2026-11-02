"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { API_URL, PAYMENT_PROVIDER } from "@/lib/config";
import { dateTime, money, ORDER_STEPS, PAYMENT_METHOD_LABEL, STATUS_LABEL } from "@/lib/format";
import type { Order, PaymentInit, TransferInstructions } from "@/lib/types";

import { CheckIcon } from "./icons";
import { Alert, PaymentBadge, Spinner, StatusBadge } from "./ui";

export function OrderSteps({ order }: { order: Order }) {
  if (order.status === "cancelled") {
    return <Alert tone="warning">This order was cancelled. Any stock was returned to the shop.</Alert>;
  }
  const current = ORDER_STEPS.indexOf(order.status);
  return (
    <ol className="grid grid-cols-5 gap-1" aria-label="Order progress">
      {ORDER_STEPS.map((step, i) => {
        const done = i <= current;
        return (
          <li key={step} className="flex flex-col items-center gap-2 text-center">
            <span
              className={`grid h-8 w-8 place-items-center rounded-full text-xs font-bold ${
                done ? "bg-brand-600 text-white" : "bg-slate-200 text-slate-500"
              } ${i === current ? "ring-4 ring-brand-100" : ""}`}
              aria-current={i === current ? "step" : undefined}
            >
              {done ? <CheckIcon width={16} height={16} /> : i + 1}
            </span>
            <span className={`text-[11px] leading-tight sm:text-xs ${done ? "font-semibold text-slate-900" : "text-slate-500"}`}>
              {STATUS_LABEL[step]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function TransferDetails({ info }: { info: TransferInstructions }) {
  const rows: [string, string | null][] = [
    ["Bank", info.bank_name],
    ["Account number", info.account_number],
    ["Account name", info.account_name],
    ["Amount", money(info.amount)],
    ["Reference", info.payment_reference],
  ];
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
      <h2 className="font-bold text-amber-900">Complete your bank transfer</h2>
      {info.account_number ? (
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt className="text-amber-800">{k}</dt>
              <dd className="font-semibold text-slate-900">{v || "—"}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-2 text-sm text-amber-900">We&apos;ll text you our account details shortly.</p>
      )}
      <p className="mt-3 text-sm text-amber-900">{info.note}</p>
    </div>
  );
}

export function OrderView({
  order,
  phone,
  instructions,
  onChange,
}: {
  order: Order;
  phone?: string; // guests prove access with the order phone
  instructions?: TransferInstructions | null;
  onChange: (o: Order) => void;
}) {
  const [busy, setBusy] = useState<"" | "pay" | "cancel">("");
  const [error, setError] = useState("");

  const canPay = order.payment_method === "card" && order.payment_status !== "paid" && order.status !== "cancelled";
  const canCancel = order.status === "pending" || order.status === "confirmed";

  async function pay() {
    setBusy("pay");
    setError("");
    try {
      const res = await api<PaymentInit>("/payments/initialize", {
        method: "POST",
        body: { order_number: order.order_number, provider: PAYMENT_PROVIDER, phone: phone ?? order.customer_phone },
      });
      window.location.assign(res.authorization_url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start the payment");
      setBusy("");
    }
  }

  async function cancel() {
    if (!window.confirm("Cancel this order?")) return;
    setBusy("cancel");
    setError("");
    try {
      onChange(
        await api<Order>(`/orders/${order.order_number}/cancel`, {
          method: "POST",
          body: { phone: phone ?? null, reason: "Cancelled by customer on the website" },
        }),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't cancel the order");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <div className="card space-y-5 p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm text-slate-500">Order</p>
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">{order.order_number}</h1>
            <p className="text-sm text-slate-500">Placed {dateTime(order.created_at)}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge status={order.status} />
            <PaymentBadge status={order.payment_status} />
          </div>
        </div>
        <OrderSteps order={order} />
        {order.status === "out_for_delivery" && (
          <Alert tone="info">
            Your rider is on the way. When they arrive, check your items, then type the code from your text message on
            their phone.
          </Alert>
        )}
        {order.status !== "cancelled" && (
          <a
            className="btn-secondary w-full sm:w-auto"
            href={`${API_URL}/track/${encodeURIComponent(order.tracking_token)}`}
            target="_blank"
            rel="noopener"
          >
            {order.status === "delivered" ? "See your delivery photo" : "Track your order live"}
          </a>
        )}
      </div>

      {order.payment_method === "transfer" && order.payment_status !== "paid" && order.status !== "cancelled" &&
        instructions && <TransferDetails info={instructions} />}

      {error && <Alert>{error}</Alert>}

      {(canPay || canCancel) && (
        <div className="flex flex-wrap gap-3">
          {canPay && (
            <button type="button" className="btn-primary px-6 py-3" onClick={pay} disabled={!!busy}>
              {busy === "pay" && <Spinner className="h-4 w-4" />}
              Pay {money(order.total)} now
            </button>
          )}
          {canCancel && (
            <button type="button" className="btn-danger" onClick={cancel} disabled={!!busy}>
              {busy === "cancel" && <Spinner className="h-4 w-4" />}
              Cancel order
            </button>
          )}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <section className="card p-5" aria-labelledby="items-h">
          <h2 id="items-h" className="mb-3 text-lg font-bold">
            Items
          </h2>
          <ul className="divide-y divide-slate-100">
            {order.items.map((i, idx) => (
              <li key={`${i.product_id}-${idx}`} className="flex justify-between gap-4 py-3 text-sm">
                <span>
                  <span className="font-medium text-slate-900">{i.product_name}</span>
                  <span className="block text-slate-500">
                    {i.quantity} × {money(i.unit_price)}
                  </span>
                </span>
                <span className="font-semibold tabular-nums">{money(i.line_total)}</span>
              </li>
            ))}
          </ul>
          <dl className="mt-3 space-y-2 border-t border-slate-100 pt-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-600">Subtotal</dt>
              <dd className="tabular-nums">{money(order.subtotal)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-600">Delivery</dt>
              <dd className="tabular-nums">{order.delivery_fee ? money(order.delivery_fee) : "Free"}</dd>
            </div>
            {order.discount_total > 0 && (
              <div className="flex justify-between text-brand-700">
                <dt>Discount</dt>
                <dd className="tabular-nums">−{money(order.discount_total)}</dd>
              </div>
            )}
            <div className="flex justify-between text-base font-bold">
              <dt>Total</dt>
              <dd className="tabular-nums">{money(order.total)}</dd>
            </div>
          </dl>
        </section>

        <section className="card space-y-4 p-5 text-sm" aria-labelledby="delivery-h">
          <h2 id="delivery-h" className="text-lg font-bold">
            Delivery
          </h2>
          <div>
            <p className="text-slate-500">To</p>
            <p className="font-medium text-slate-900">{order.customer_name}</p>
            <p className="text-slate-700">{order.delivery_address}</p>
          </div>
          {order.notes && (
            <div>
              <p className="text-slate-500">Notes</p>
              <p className="text-slate-700">{order.notes}</p>
            </div>
          )}
          <div>
            <p className="text-slate-500">Payment</p>
            <p className="font-medium text-slate-900">{PAYMENT_METHOD_LABEL[order.payment_method]}</p>
          </div>
        </section>
      </div>
    </div>
  );
}
