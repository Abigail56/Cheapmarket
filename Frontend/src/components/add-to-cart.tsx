"use client";

import { useState } from "react";

import { useCart } from "@/providers/cart";
import { useToast } from "@/providers/toast";

import { MinusIcon, PlusIcon } from "./icons";
import { Spinner } from "./ui";

export function QuantityStepper({
  value,
  onChange,
  disabled,
  size = "md",
  label,
}: {
  value: number;
  onChange: (n: number) => void;
  disabled?: boolean;
  size?: "sm" | "md";
  label: string;
}) {
  const box = size === "sm" ? "h-8 w-8" : "h-10 w-10";
  return (
    <div className="inline-flex items-center rounded-xl border border-slate-300 bg-white">
      <button
        type="button"
        className={`grid ${box} place-items-center rounded-l-xl text-slate-700 hover:bg-slate-50 disabled:opacity-50`}
        onClick={() => onChange(value - 1)}
        disabled={disabled}
        aria-label={`One less ${label}`}
      >
        <MinusIcon width={16} height={16} />
      </button>
      <span className="min-w-8 text-center text-sm font-semibold tabular-nums" aria-live="polite">
        {value}
      </span>
      <button
        type="button"
        className={`grid ${box} place-items-center rounded-r-xl text-slate-700 hover:bg-slate-50 disabled:opacity-50`}
        onClick={() => onChange(value + 1)}
        disabled={disabled}
        aria-label={`One more ${label}`}
      >
        <PlusIcon width={16} height={16} />
      </button>
    </div>
  );
}

// "Add" button that turns into a quantity stepper once the product is in the cart
export function AddToCart({
  productId,
  name,
  inStock,
  size = "sm",
}: {
  productId: string;
  name: string;
  inStock: boolean;
  size?: "sm" | "md";
}) {
  const { add, setQuantity, remove, quantityOf } = useCart();
  const toast = useToast();
  const [pending, setPending] = useState(false);
  const qty = quantityOf(productId);

  if (!inStock) {
    return (
      <span className="inline-flex rounded-xl bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-500">
        Out of stock
      </span>
    );
  }

  const act = async (fn: () => Promise<void>, done?: string) => {
    setPending(true);
    try {
      await fn();
      if (done) toast(done);
    } catch {
      /* the cart already showed the error */
    } finally {
      setPending(false);
    }
  };

  if (qty > 0) {
    return (
      <QuantityStepper
        value={qty}
        size={size}
        label={name}
        disabled={pending}
        onChange={(n) => act(() => (n <= 0 ? remove(productId) : setQuantity(productId, n)))}
      />
    );
  }

  return (
    <button
      type="button"
      className={`btn-primary ${size === "sm" ? "px-3 py-2" : "w-full py-3 text-base"}`}
      disabled={pending}
      onClick={() => act(() => add(productId, 1), `${name} added to cart`)}
    >
      {pending ? <Spinner className="h-4 w-4" /> : null}
      Add to cart
    </button>
  );
}
