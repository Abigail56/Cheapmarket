"use client";

import { useState } from "react";

import { Alert, Field, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Order } from "@/lib/types";

// Guests see an order only after giving the phone number used at checkout
export function PhoneGate({
  orderNumber,
  onFound,
}: {
  orderNumber?: string;
  onFound: (order: Order, phone: string) => void;
}) {
  const [number, setNumber] = useState(orderNumber ?? "");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!number.trim() || phone.replace(/\D/g, "").length < 7) {
      setError("Enter the order number and the phone number used for the order.");
      return;
    }
    setBusy(true);
    try {
      const order = await api<Order>("/orders/track", {
        method: "POST",
        body: { order_number: number.trim().toUpperCase(), phone: phone.trim() },
        auth: false,
      });
      onFound(order, order.customer_phone);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 404
          ? "No order matches that number and phone. Check both and try again."
          : err instanceof Error
            ? err.message
            : "Couldn't look up the order",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card mx-auto max-w-md space-y-4 p-6" noValidate>
      <div>
        <h1 className="text-xl font-extrabold text-slate-900">Find your order</h1>
        <p className="mt-1 text-sm text-slate-600">
          Enter your order number (it&apos;s in your SMS, like <span className="font-mono">CMD-1A2B3C4D</span>) and the
          phone number you ordered with.
        </p>
      </div>
      {!orderNumber && (
        <Field label="Order number" htmlFor="order-number">
          <input
            id="order-number"
            className="input uppercase"
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="CMD-1A2B3C4D"
            autoComplete="off"
          />
        </Field>
      )}
      <Field label="Phone number" htmlFor="track-phone">
        <input
          id="track-phone"
          className="input"
          type="tel"
          inputMode="tel"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="0803 123 4567"
          autoComplete="tel"
        />
      </Field>
      {error && <Alert>{error}</Alert>}
      <button className="btn-primary w-full py-3" disabled={busy}>
        {busy && <Spinner className="h-4 w-4" />}
        Show my order
      </button>
    </form>
  );
}
