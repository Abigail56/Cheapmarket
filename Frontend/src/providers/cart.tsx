"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { cartSessionStore, tokenStore } from "@/lib/storage";
import type { Cart } from "@/lib/types";

import { onAuthChange } from "./auth";
import { useToast } from "./toast";

const EMPTY: Cart = { session_id: null, items: [], item_count: 0, subtotal: 0 };

interface CartState {
  cart: Cart;
  ready: boolean;
  busy: boolean;
  add: (productId: string, quantity?: number) => Promise<void>;
  setQuantity: (productId: string, quantity: number) => Promise<void>;
  remove: (productId: string) => Promise<void>;
  clear: () => Promise<void>;
  reload: () => Promise<void>;
  quantityOf: (productId: string) => number;
}

const CartContext = createContext<CartState | null>(null);

export function useCart(): CartState {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart outside CartProvider");
  return ctx;
}

export function CartProvider({ children }: { children: React.ReactNode }) {
  const toast = useToast();
  const [cart, setCart] = useState<Cart>(EMPTY);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  const accept = useCallback(
    (c: Cart) => {
      // A guest's first add creates the cart: keep its id for later calls
      if (c.session_id && !tokenStore.get()) cartSessionStore.set(c.session_id);
      setCart(c);
      for (const n of c.notices ?? []) toast(n, "info"); // e.g. "only 3 left, quantity reduced"
    },
    [toast],
  );

  const reload = useCallback(async () => {
    if (!tokenStore.get() && !cartSessionStore.get()) {
      setCart(EMPTY);
      return;
    }
    try {
      accept(await api<Cart>("/cart", { cart: true }));
    } catch {
      /* keep what we have */
    }
  }, [accept]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await reload();
      if (!cancelled) setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  // Signing in: move the guest cart into the account. Signing out: forget the cart
  useEffect(
    () =>
      onAuthChange(async (user) => {
        const guest = cartSessionStore.get();
        if (user && guest) {
          try {
            accept(await api<Cart>("/cart/merge", { method: "POST", body: { session_id: guest } }));
            cartSessionStore.set(null);
            return;
          } catch {
            /* fall through to a normal reload */
          }
        }
        if (!user) cartSessionStore.set(null);
        await reload();
      }),
    [accept, reload],
  );

  const run = useCallback(
    async (fn: () => Promise<Cart>) => {
      setBusy(true);
      try {
        accept(await fn());
      } catch (e) {
        toast(e instanceof Error ? e.message : "Couldn't update your cart", "error");
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [accept, toast],
  );

  const value = useMemo<CartState>(
    () => ({
      cart,
      ready,
      busy,
      reload,
      add: (product_id, quantity = 1) =>
        run(() => api<Cart>("/cart/items", { method: "POST", body: { product_id, quantity }, cart: true })),
      setQuantity: (id, quantity) =>
        run(() => api<Cart>(`/cart/items/${id}`, { method: "PUT", body: { quantity }, cart: true })),
      remove: (id) => run(() => api<Cart>(`/cart/items/${id}`, { method: "DELETE", cart: true })),
      clear: () => run(() => api<Cart>("/cart", { method: "DELETE", cart: true })),
      quantityOf: (id) => cart.items.find((i) => i.product.id === id)?.quantity ?? 0,
    }),
    [cart, ready, busy, reload, run],
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}
