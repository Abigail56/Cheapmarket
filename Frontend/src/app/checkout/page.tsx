"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ProductImage } from "@/components/product-image";
import { Alert, EmptyState, Field, PageLoading, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { PAYMENT_PROVIDER } from "@/lib/config";
import { localPhone, money } from "@/lib/format";
import { orderAccessStore } from "@/lib/storage";
import type { Address, CheckoutResponse, PaymentInit, PaymentMethod, Quote, Zone } from "@/lib/types";
import { useAuth } from "@/providers/auth";
import { useCart } from "@/providers/cart";

const NEW = "new";

const METHODS: { value: PaymentMethod; title: string; text: string }[] = [
  { value: "card", title: "Pay online now", text: "Pay by card, bank or USSD" },
  { value: "cod", title: "Pay on delivery", text: "Pay the rider in cash or by transfer when it arrives" },
  { value: "transfer", title: "Bank transfer", text: "We confirm your order once we receive your transfer" },
];

export default function CheckoutPage() {
  const router = useRouter();
  const { user, ready: authReady } = useAuth();
  const { cart, ready: cartReady, reload } = useCart();

  const [zones, setZones] = useState<Zone[]>([]);
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [loaded, setLoaded] = useState(false);

  // Form
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [addressId, setAddressId] = useState<string>(NEW);
  const [street, setStreet] = useState("");
  const [landmark, setLandmark] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");
  const [zoneId, setZoneId] = useState("");
  const [saveAddress, setSaveAddress] = useState(true);
  const [method, setMethod] = useState<PaymentMethod>("cod");
  const [notes, setNotes] = useState("");
  const [couponInput, setCouponInput] = useState("");
  const [coupon, setCoupon] = useState("");

  const [lastQuote, setQuote] = useState<Quote | null>(null);
  const [quoteError, setQuoteError] = useState("");
  const [couponError, setCouponError] = useState(""); // kept apart: re-pricing without the coupon must not clear it
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [placing, setPlacing] = useState(false);

  // Zones for everyone; saved addresses and contact details for signed-in customers
  useEffect(() => {
    if (!authReady) return;
    let cancelled = false;
    (async () => {
      const [z, a] = await Promise.all([
        api<Zone[]>("/delivery-zones", { auth: false }).catch(() => [] as Zone[]),
        user ? api<Address[]>("/users/me/addresses").catch(() => [] as Address[]) : Promise.resolve([] as Address[]),
      ]);
      if (cancelled) return;
      setZones(z.filter((x) => x.is_active));
      setAddresses(a);
      if (user) {
        setName((v) => v || user.full_name);
        setEmail((v) => v || user.email);
        setPhone((v) => v || localPhone(user.phone));
        const preferred = a.find((x) => x.is_default) ?? a[0];
        if (preferred) {
          setAddressId(preferred.id);
          if (preferred.zone_id) setZoneId(preferred.zone_id);
          if (preferred.phone) setPhone((v) => v || localPhone(preferred.phone));
        }
      }
      setLoaded(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [authReady, user]);

  const selectedAddress = addresses.find((a) => a.id === addressId) ?? null;

  // Price the cart on the server whenever the zone, coupon or cart changes
  useEffect(() => {
    if (!zoneId || !cart.items.length) return;
    let cancelled = false;
    api<Quote>("/checkout/quote", {
      method: "POST",
      body: { zone_id: zoneId, coupon_code: coupon || null },
      cart: true,
    })
      .then((q) => {
        if (cancelled) return;
        setQuote(q);
        setQuoteError("");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (coupon) {
          // A bad coupon shouldn't block checkout: drop it and re-price without it
          setCouponError(e instanceof ApiError ? e.message : "That coupon can't be used");
          setCoupon("");
        } else {
          setQuote(null);
          setQuoteError(e instanceof ApiError ? e.message : "Couldn't price your order");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [zoneId, coupon, cart.subtotal, cart.items.length]);

  // Only show a price for the current zone choice
  const quote = zoneId ? lastQuote : null;

  const zone = useMemo(() => zones.find((z) => z.id === zoneId) ?? null, [zones, zoneId]);

  if (!cartReady || !authReady || !loaded) return <PageLoading />;

  if (!cart.items.length) {
    return (
      <div className="container-page py-12">
        <EmptyState
          title="Your cart is empty"
          action={
            <Link href="/shop" className="btn-primary">
              Go shopping
            </Link>
          }
        >
          Add something to your cart before checking out.
        </EmptyState>
      </div>
    );
  }

  function validate(): Record<string, string> {
    const e: Record<string, string> = {};
    if (name.trim().length < 2) e.name = "Enter your full name";
    if (phone.replace(/\D/g, "").length < 10) e.phone = "Enter a phone number we can call or text";
    if (method === "card" && !email.trim()) e.email = "An email is needed for online payment receipts";
    if (email && !/^\S+@\S+\.\S+$/.test(email.trim())) e.email = "Enter a valid email";
    if (addressId === NEW) {
      if (street.trim().length < 3) e.street = "Enter your street address";
      if (city.trim().length < 2) e.city = "Enter your city or area";
      if (stateName.trim().length < 2) e.state = "Enter your state";
    }
    if (!zoneId) e.zone = "Choose your delivery zone";
    return e;
  }

  async function placeOrder(ev: React.FormEvent) {
    ev.preventDefault();
    setFormError("");
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length) {
      setFormError("Please fix the highlighted fields.");
      return;
    }
    setPlacing(true);
    try {
      let useAddressId = selectedAddress?.id ?? null;
      // Signed-in customers can keep a typed address for next time
      if (!useAddressId && user && saveAddress) {
        const saved = await api<Address>("/users/me/addresses", {
          method: "POST",
          body: {
            label: "Home",
            street: street.trim(),
            landmark: landmark.trim() || null,
            city: city.trim(),
            state: stateName.trim(),
            zone_id: zoneId,
            phone: phone.trim(),
            is_default: addresses.length === 0,
          },
        }).catch(() => null); // saving is a convenience: never block the order on it
        useAddressId = saved?.id ?? null;
      }
      const typed = [street, landmark, city, stateName].map((s) => s.trim()).filter(Boolean).join(", ");
      const res = await api<CheckoutResponse>("/orders", {
        method: "POST",
        cart: true,
        body: {
          customer_name: name.trim(),
          customer_phone: phone.trim(),
          customer_email: email.trim() || null,
          address_id: useAddressId,
          delivery_address: useAddressId ? null : typed,
          zone_id: zoneId,
          payment_method: method,
          coupon_code: coupon || null,
          notes: notes.trim() || null,
        },
      });
      const order = res.order;
      orderAccessStore.set(order.order_number, { phone: order.customer_phone, instructions: res.payment_instructions });
      await reload(); // the server emptied the cart

      if (res.next_step === "pay_online") {
        try {
          const pay = await api<PaymentInit>("/payments/initialize", {
            method: "POST",
            body: { order_number: order.order_number, provider: PAYMENT_PROVIDER, phone: order.customer_phone },
          });
          window.location.assign(pay.authorization_url);
          return;
        } catch {
          // The order exists: let them retry payment from the order page
          router.push(`/orders/${order.order_number}?placed=1&pay=retry`);
          return;
        }
      }
      router.push(`/orders/${order.order_number}?placed=1`);
    } catch (err) {
      setPlacing(false);
      if (err instanceof ApiError) {
        setErrors(err.fields);
        setFormError(err.message);
      } else {
        setFormError("Couldn't place your order. Please try again.");
      }
    }
  }

  return (
    <div className="container-page py-8">
      <h1 className="mb-6 text-2xl font-extrabold tracking-tight text-slate-900">Checkout</h1>

      {!user && (
        <div className="mb-6">
          <Alert tone="info">
            Checking out as a guest.{" "}
            <Link href="/login?next=/checkout" className="link">
              Sign in
            </Link>{" "}
            to use saved addresses and see your order history.
          </Alert>
        </div>
      )}

      <form onSubmit={placeOrder} noValidate className="grid gap-8 lg:grid-cols-[1fr_380px] lg:items-start">
        <div className="space-y-6">
          <section className="card space-y-4 p-5" aria-labelledby="contact-h">
            <h2 id="contact-h" className="text-lg font-bold">
              1. Your details
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Full name" htmlFor="name" error={errors.name}>
                <input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
              </Field>
              <Field label="Phone number" htmlFor="phone" error={errors.phone} hint="For delivery updates by SMS">
                <input
                  id="phone"
                  className="input"
                  type="tel"
                  inputMode="tel"
                  placeholder="0803 123 4567"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  autoComplete="tel"
                />
              </Field>
              <div className="sm:col-span-2">
                <Field
                  label={method === "card" ? "Email" : "Email (optional)"}
                  htmlFor="email"
                  error={errors.email}
                  hint="We'll send your receipt here"
                >
                  <input
                    id="email"
                    className="input"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                  />
                </Field>
              </div>
            </div>
          </section>

          <section className="card space-y-4 p-5" aria-labelledby="delivery-h">
            <h2 id="delivery-h" className="text-lg font-bold">
              2. Delivery address
            </h2>

            {addresses.length > 0 && (
              <fieldset className="space-y-2">
                <legend className="sr-only">Choose an address</legend>
                {addresses.map((a) => (
                  <label
                    key={a.id}
                    className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-sm ${
                      addressId === a.id ? "border-brand-500 bg-brand-50" : "border-slate-200"
                    }`}
                  >
                    <input
                      type="radio"
                      name="address"
                      className="mt-1 accent-brand-600"
                      checked={addressId === a.id}
                      onChange={() => {
                        setAddressId(a.id);
                        if (a.zone_id) setZoneId(a.zone_id);
                      }}
                    />
                    <span>
                      <span className="font-semibold">{a.label}</span>
                      <span className="block text-slate-600">
                        {[a.street, a.landmark, a.city, a.state].filter(Boolean).join(", ")}
                      </span>
                    </span>
                  </label>
                ))}
                <label
                  className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-sm ${
                    addressId === NEW ? "border-brand-500 bg-brand-50" : "border-slate-200"
                  }`}
                >
                  <input
                    type="radio"
                    name="address"
                    className="accent-brand-600"
                    checked={addressId === NEW}
                    onChange={() => setAddressId(NEW)}
                  />
                  <span className="font-semibold">Deliver somewhere else</span>
                </label>
              </fieldset>
            )}

            {addressId === NEW && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <Field label="Street address" htmlFor="street" error={errors.street}>
                    <input
                      id="street"
                      className="input"
                      placeholder="12 Adeola Odeku Street"
                      value={street}
                      onChange={(e) => setStreet(e.target.value)}
                      autoComplete="street-address"
                    />
                  </Field>
                </div>
                <div className="sm:col-span-2">
                  <Field label="Landmark (optional)" htmlFor="landmark" hint="Helps the rider find you, e.g. 'opposite GTBank'">
                    <input id="landmark" className="input" value={landmark} onChange={(e) => setLandmark(e.target.value)} />
                  </Field>
                </div>
                <Field label="City / area" htmlFor="city" error={errors.city}>
                  <input id="city" className="input" value={city} onChange={(e) => setCity(e.target.value)} autoComplete="address-level2" />
                </Field>
                <Field label="State" htmlFor="state" error={errors.state}>
                  <input
                    id="state"
                    className="input"
                    placeholder="Lagos"
                    value={stateName}
                    onChange={(e) => setStateName(e.target.value)}
                    autoComplete="address-level1"
                  />
                </Field>
                {user && (
                  <label className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-brand-600"
                      checked={saveAddress}
                      onChange={(e) => setSaveAddress(e.target.checked)}
                    />
                    Save this address for next time
                  </label>
                )}
              </div>
            )}

            <Field
              label="Delivery zone"
              htmlFor="zone"
              error={errors.zone}
              hint={
                zone?.free_delivery_min
                  ? `Free delivery in this zone on orders over ${money(zone.free_delivery_min)}`
                  : "Sets your delivery fee"
              }
            >
              <select id="zone" className="input" value={zoneId} onChange={(e) => setZoneId(e.target.value)}>
                <option value="">Choose your zone…</option>
                {zones.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.name}: {money(z.delivery_fee)}
                  </option>
                ))}
              </select>
            </Field>
            {!zones.length && <Alert tone="warning">Delivery zones couldn&apos;t load. Please refresh the page.</Alert>}

            <Field label="Delivery notes (optional)" htmlFor="notes" hint="Gate code, best time to call…">
              <textarea
                id="notes"
                className="input min-h-20"
                maxLength={500}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </Field>
          </section>

          <section className="card space-y-3 p-5" aria-labelledby="pay-h">
            <h2 id="pay-h" className="text-lg font-bold">
              3. Payment
            </h2>
            <fieldset className="grid gap-2">
              <legend className="sr-only">Payment method</legend>
              {METHODS.map((m) => (
                <label
                  key={m.value}
                  className={`flex cursor-pointer gap-3 rounded-xl border p-4 text-sm ${
                    method === m.value ? "border-brand-500 bg-brand-50" : "border-slate-200"
                  }`}
                >
                  <input
                    type="radio"
                    name="method"
                    className="mt-1 accent-brand-600"
                    checked={method === m.value}
                    onChange={() => setMethod(m.value)}
                  />
                  <span>
                    <span className="font-semibold text-slate-900">{m.title}</span>
                    <span className="block text-slate-600">{m.text}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          </section>
        </div>

        <aside className="card space-y-4 p-5 lg:sticky lg:top-28">
          <h2 className="text-lg font-bold">Order summary</h2>
          <ul className="max-h-64 space-y-3 overflow-y-auto pr-1">
            {cart.items.map((i) => (
              <li key={i.product.id} className="flex items-center gap-3 text-sm">
                <ProductImage src={i.product.image_url} alt="" className="h-12 w-12 shrink-0 rounded-lg" />
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-1 font-medium">{i.product.name}</span>
                  <span className="text-slate-500">× {i.quantity}</span>
                </span>
                <span className="font-semibold tabular-nums">{money(i.line_total)}</span>
              </li>
            ))}
          </ul>

          <div className="space-y-2 border-t border-slate-100 pt-4">
            <label htmlFor="coupon" className="label">
              Coupon code
            </label>
            <div className="flex gap-2">
              <input
                id="coupon"
                className="input uppercase"
                value={couponInput}
                onChange={(e) => setCouponInput(e.target.value)}
                placeholder="WELCOME10"
              />
              <button
                type="button"
                className="btn-secondary"
                disabled={!couponInput.trim() || !zoneId}
                onClick={() => {
                  setCouponError("");
                  setCoupon(couponInput.trim().toUpperCase());
                }}
              >
                Apply
              </button>
            </div>
            {!zoneId && couponInput && <p className="text-xs text-slate-500">Choose a delivery zone first.</p>}
            {quote?.coupon_applied && (
              <p className="text-xs font-medium text-brand-700">
                {quote.coupon_applied} applied.{" "}
                <button
                  type="button"
                  className="underline"
                  onClick={() => {
                    setCoupon("");
                    setCouponInput("");
                  }}
                >
                  Remove
                </button>
              </p>
            )}
            {couponError && <p className="text-xs text-red-600">{couponError}</p>}
            {quoteError && <p className="text-xs text-red-600">{quoteError}</p>}
          </div>

          <dl className="space-y-2 border-t border-slate-100 pt-4 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-600">Subtotal</dt>
              <dd className="tabular-nums">{money(quote?.subtotal ?? cart.subtotal)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-600">Delivery{zone ? ` (${zone.name})` : ""}</dt>
              <dd className="tabular-nums">
                {quote ? (quote.delivery_fee === 0 ? "Free" : money(quote.delivery_fee)) : "Choose a zone"}
              </dd>
            </div>
            {quote && quote.discount_total > 0 && (
              <div className="flex justify-between text-brand-700">
                <dt>Discount</dt>
                <dd className="tabular-nums">−{money(quote.discount_total)}</dd>
              </div>
            )}
            <div className="flex justify-between border-t border-slate-100 pt-3 text-base font-bold">
              <dt>Total</dt>
              <dd className="tabular-nums">{money(quote?.total ?? cart.subtotal)}</dd>
            </div>
          </dl>
          {quote?.free_delivery_remaining ? (
            <p className="rounded-lg bg-brand-50 p-2 text-xs text-brand-800">
              Add {money(quote.free_delivery_remaining)} more for free delivery.
            </p>
          ) : null}

          {formError && <Alert>{formError}</Alert>}

          <button type="submit" className="btn-primary w-full py-3 text-base" disabled={placing}>
            {placing && <Spinner className="h-4 w-4" />}
            {method === "card" ? "Place order & pay" : "Place order"}
          </button>
          <p className="text-center text-xs text-slate-500">Your final total is confirmed when you place the order.</p>
        </aside>
      </form>
    </div>
  );
}
