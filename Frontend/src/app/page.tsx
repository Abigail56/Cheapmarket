import Link from "next/link";
import { Suspense } from "react";

import { ChevronRight } from "@/components/icons";
import { ProductImage } from "@/components/product-image";
import { ProductGrid, ProductGridSkeleton } from "@/components/product-card";
import { getCategories, getProducts, getZones } from "@/lib/catalog";
import { money } from "@/lib/format";

export default function HomePage() {
  return (
    <>
      <Hero />

      <section className="container-page mt-16" aria-labelledby="cat-heading">
        <SectionHeading id="cat-heading" title="Shop by category" href="/shop" />
        <Suspense fallback={<div className="h-32 animate-pulse rounded-2xl bg-slate-100" />}>
          <Categories />
        </Suspense>
      </section>

      <section className="container-page mt-20" aria-labelledby="featured-heading">
        <SectionHeading id="featured-heading" title="Featured products" href="/shop" />
        <Suspense fallback={<ProductGridSkeleton count={4} />}>
          <ProductsRow featured />
        </Suspense>
      </section>

      <Promises />

      <section className="container-page mt-20" aria-labelledby="new-heading">
        <SectionHeading id="new-heading" title="New products" href="/shop?sort=newest" />
        <Suspense fallback={<ProductGridSkeleton count={8} />}>
          <ProductsRow size={8} />
        </Suspense>
      </section>

      <Suspense fallback={null}>
        <DeliveryZones />
      </Suspense>
    </>
  );
}

function Hero() {
  return (
    <>
      <section className="relative isolate overflow-hidden bg-brand-950 text-white">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/images/hero.jpg"
          alt=""
          fetchPriority="high"
          className="absolute inset-0 -z-10 h-full w-full object-cover"
        />
        <div className="absolute inset-0 -z-10 bg-linear-to-r from-brand-950/95 via-brand-950/80 to-brand-950/70 sm:via-brand-950/70 sm:to-brand-950/20" />
        <div className="container-page pb-32 pt-20 sm:pb-40 sm:pt-28 lg:pt-36">
          <div className="max-w-2xl">
            <h1 className="text-balance text-5xl font-semibold leading-[1.05] sm:text-6xl lg:text-7xl">
              Groceries delivered to your door
            </h1>
            <p className="mt-6 max-w-xl text-lg text-white/85">
              Order foodstuff, fresh produce and household items online. Pay by card, by bank transfer or on delivery,
              and follow your rider on a map.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link href="/shop" className="btn bg-amber-400 px-7 py-3.5 text-base text-brand-950 hover:bg-amber-300">
                Shop now <ChevronRight width={18} height={18} />
              </Link>
              <Link
                href="/track"
                className="btn border border-white/50 px-7 py-3.5 text-base text-white hover:bg-white/10"
              >
                Track an order
              </Link>
            </div>
          </div>
        </div>
      </section>
      <div className="container-page relative z-10 -mt-20">
        <ul className="grid grid-cols-1 gap-x-8 gap-y-5 rounded-2xl bg-white p-6 shadow-xl sm:grid-cols-2 sm:p-8 lg:grid-cols-4">
          {[
            ["Pay on delivery", "Pay the rider in cash or by transfer"],
            ["Rider tracking", "Follow your order on a map"],
            ["Delivery code", "Confirm your delivery with a code sent by SMS"],
            ["Online payment", "Pay by card, bank transfer or USSD"],
          ].map(([title, text]) => (
            <li key={title}>
              <p className="font-semibold text-slate-900">{title}</p>
              <p className="mt-1 text-sm text-slate-600">{text}</p>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}

function SectionHeading({ id, title, href }: { id: string; title: string; href: string }) {
  return (
    <div className="mb-7 flex items-end justify-between gap-4">
      <h2 id={id} className="text-3xl font-semibold text-slate-900 sm:text-4xl">
        {title}
      </h2>
      <Link href={href} className="link inline-flex items-center gap-1 text-sm">
        See all <ChevronRight width={16} height={16} />
      </Link>
    </div>
  );
}

async function Categories() {
  const categories = await getCategories().catch(() => []);
  const top = categories.filter((c) => !c.parent_id);
  if (!top.length) return <p className="text-sm text-slate-500">Categories will appear here soon.</p>;
  return (
    <ul className="grid grid-cols-2 gap-3 sm:gap-5 md:grid-cols-3">
      {top.map((c) => (
        <li key={c.id}>
          <Link
            href={`/shop?category=${c.slug}`}
            className="group relative block overflow-hidden rounded-2xl bg-brand-900"
          >
            <ProductImage
              src={c.image_url}
              alt=""
              className="block aspect-[4/3] w-full transition duration-500 group-hover:scale-105"
            />
            <span className="absolute inset-0 bg-linear-to-t from-black/75 via-black/15 to-transparent" />
            <span className="absolute inset-x-0 bottom-0 p-4 text-xl font-semibold tracking-tight text-white sm:p-5 sm:text-2xl">
              {c.name}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

async function ProductsRow({ featured, size = 4 }: { featured?: boolean; size?: number }) {
  let page = await getProducts({ featured, size, in_stock_only: true }).catch(() => null);
  // No featured products yet: show the newest ones instead of an empty row
  if (featured && page && !page.items.length) page = await getProducts({ size, in_stock_only: true }).catch(() => null);
  if (!page) return <p className="text-sm text-slate-500">Products couldn&apos;t load. Please refresh the page.</p>;
  if (!page.items.length) return <p className="text-sm text-slate-500">No products are available right now.</p>;
  return <ProductGrid products={page.items} />;
}

function Promises() {
  const steps = [
    ["Place your order", "Add your items to the cart and choose your delivery area."],
    ["Choose how to pay", "Pay online, by bank transfer or when your order arrives."],
    ["Receive your delivery", "Check your items and confirm with the code we send you by SMS."],
  ];
  return (
    <section className="relative isolate mt-20 overflow-hidden bg-brand-950 text-white">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/images/market.jpg" alt="" loading="lazy" className="absolute inset-0 -z-10 h-full w-full object-cover" />
      <div className="absolute inset-0 -z-10 bg-brand-950/85" />
      <div className="container-page py-16 sm:py-20">
        <h2 className="text-3xl font-semibold sm:text-4xl">How delivery works</h2>
        <ol className="mt-10 grid gap-8 sm:grid-cols-3">
          {steps.map(([title, text], i) => (
            <li key={title} className="border-t border-white/30 pt-4">
              <p className="text-sm text-white/70">Step {i + 1}</p>
              <p className="mt-1 text-lg font-semibold">{title}</p>
              <p className="mt-1 text-sm text-white/80">{text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

async function DeliveryZones() {
  const zones = (await getZones().catch(() => [])).filter((z) => z.is_active);
  if (!zones.length) return null;
  return (
    <section className="container-page mt-20" aria-labelledby="zones-heading">
      <div className="card p-6 sm:p-8">
        <h2 id="zones-heading" className="text-3xl font-semibold text-slate-900">
          Delivery areas
        </h2>
        <p className="mt-1 text-sm text-slate-600">Fees vary by area. You&apos;ll choose yours at checkout.</p>
        <ul className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {zones.map((z) => (
            <li key={z.id} className="rounded-xl border border-slate-200 p-4">
              <p className="font-semibold text-slate-900">{z.name}</p>
              <p className="text-sm text-slate-600">
                {money(z.delivery_fee)} delivery
                {z.free_delivery_min ? (
                  <span className="text-brand-700"> · free over {money(z.free_delivery_min)}</span>
                ) : null}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
