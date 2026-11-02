"use client";

import Link from "next/link";

import { QuantityStepper } from "@/components/add-to-cart";
import { TrashIcon } from "@/components/icons";
import { ProductImage } from "@/components/product-image";
import { EmptyState, PageLoading } from "@/components/ui";
import { money } from "@/lib/format";
import { useCart } from "@/providers/cart";

export default function CartPage() {
  const { cart, ready, busy, setQuantity, remove, clear } = useCart();

  if (!ready) return <PageLoading />;

  if (!cart.items.length) {
    return (
      <div className="container-page py-12">
        <EmptyState
          title="Your cart is empty"
          action={
            <Link href="/shop" className="btn-primary">
              Start shopping
            </Link>
          }
        >
          Items you add will appear here.
        </EmptyState>
      </div>
    );
  }

  const unavailable = cart.items.some((i) => !i.product.in_stock);

  return (
    <div className="container-page py-8">
      <h1 className="mb-6 text-2xl font-extrabold tracking-tight text-slate-900">Your cart</h1>
      <div className="grid gap-8 lg:grid-cols-[1fr_360px] lg:items-start">
        <section className="card divide-y divide-slate-100" aria-label="Items">
          {cart.items.map(({ product, quantity, line_total }) => (
            <div key={product.id} className="flex gap-4 p-4">
              <Link href={`/products/${product.slug}`} className="shrink-0">
                <ProductImage src={product.image_url} alt={product.name} className="h-20 w-20 rounded-xl sm:h-24 sm:w-24" />
              </Link>
              <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <Link href={`/products/${product.slug}`} className="font-semibold text-slate-900 hover:text-brand-700">
                    {product.name}
                  </Link>
                  <p className="text-sm text-slate-500">
                    {product.unit} · {money(product.price)} each
                  </p>
                  {!product.in_stock && <p className="text-sm font-medium text-red-600">No longer in stock</p>}
                </div>
                <div className="flex items-center justify-between gap-4 sm:justify-end">
                  <QuantityStepper
                    value={quantity}
                    size="sm"
                    label={product.name}
                    disabled={busy}
                    onChange={(n) => (n <= 0 ? remove(product.id) : setQuantity(product.id, n)).catch(() => {})}
                  />
                  <p className="w-24 text-right font-bold tabular-nums text-slate-900">{money(line_total)}</p>
                  <button
                    type="button"
                    className="btn-ghost p-2 text-slate-400 hover:text-red-600"
                    onClick={() => remove(product.id).catch(() => {})}
                    disabled={busy}
                    aria-label={`Remove ${product.name}`}
                  >
                    <TrashIcon width={18} height={18} />
                  </button>
                </div>
              </div>
            </div>
          ))}
          <div className="flex justify-between p-4">
            <Link href="/shop" className="link text-sm">
              ← Keep shopping
            </Link>
            <button
              type="button"
              className="text-sm text-slate-500 hover:text-red-600"
              onClick={() => {
                if (window.confirm("Remove everything from your cart?")) clear().catch(() => {});
              }}
              disabled={busy}
            >
              Empty cart
            </button>
          </div>
        </section>

        <aside className="card space-y-4 p-5 lg:sticky lg:top-28">
          <h2 className="text-lg font-bold text-slate-900">Summary</h2>
          <div className="flex justify-between text-sm">
            <span className="text-slate-600">
              Subtotal ({cart.item_count} {cart.item_count === 1 ? "item" : "items"})
            </span>
            <span className="font-semibold tabular-nums">{money(cart.subtotal)}</span>
          </div>
          <p className="text-xs text-slate-500">Delivery fee and any coupon are added at checkout.</p>
          {unavailable && (
            <p className="text-sm text-red-600">Remove items that are out of stock to continue.</p>
          )}
          {unavailable ? (
            <span className="btn-primary pointer-events-none w-full py-3 opacity-60" aria-disabled="true">
              Checkout
            </span>
          ) : (
            <Link href="/checkout" className="btn-primary w-full py-3 text-base">
              Checkout
            </Link>
          )}
        </aside>
      </div>
    </div>
  );
}
