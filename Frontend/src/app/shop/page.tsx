import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { ProductGrid, ProductGridSkeleton } from "@/components/product-card";
import { EmptyState } from "@/components/ui";
import { getCategories, getProducts, type ProductQuery } from "@/lib/catalog";
import type { Category, ProductSort } from "@/lib/types";

import { SortSelect } from "./sort-select";

export const metadata: Metadata = {
  title: "Shop",
  description: "Groceries, fresh produce and household items.",
};

type Search = Record<string, string | string[] | undefined>;

const SORTS: ProductSort[] = ["newest", "price_asc", "price_desc", "name"];

function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v || undefined;
}

function parse(sp: Search): ProductQuery {
  const sort = one(sp.sort) as ProductSort | undefined;
  const page = Number(one(sp.page));
  const price = (v?: string) => (v && /^\d+(\.\d+)?$/.test(v) ? v : undefined);
  return {
    q: one(sp.q)?.slice(0, 100),
    category: one(sp.category),
    sort: sort && SORTS.includes(sort) ? sort : "newest",
    min_price: price(one(sp.min_price)),
    max_price: price(one(sp.max_price)),
    in_stock_only: one(sp.in_stock) === "1",
    page: Number.isInteger(page) && page > 1 ? page : 1,
    size: 24,
  };
}

// Builds a /shop link that keeps the current filters, with some changed
function shopHref(query: ProductQuery, changes: Partial<Record<keyof ProductQuery, string | undefined>>) {
  const merged: Record<string, string | undefined> = {
    q: query.q,
    category: query.category,
    sort: query.sort === "newest" ? undefined : query.sort,
    min_price: query.min_price,
    max_price: query.max_price,
    in_stock: query.in_stock_only ? "1" : undefined,
    page: undefined, // any filter change goes back to page 1
    ...changes,
  };
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(merged)) if (v) params.set(k, v);
  const qs = params.toString();
  return `/shop${qs ? `?${qs}` : ""}`;
}

export default function ShopPage({ searchParams }: PageProps<"/shop">) {
  return (
    <div className="container-page py-8">
      <Suspense fallback={<ShopSkeleton />}>
        <Shop searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

function ShopSkeleton() {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[240px_minmax(0,1fr)]">
      <div className="hidden h-96 animate-pulse rounded-2xl bg-slate-100 lg:block" />
      <ProductGridSkeleton count={8} />
    </div>
  );
}

async function Shop({ searchParams }: { searchParams: Promise<Search> }) {
  const query = parse(await searchParams);
  const [categories, result] = await Promise.all([
    getCategories().catch(() => [] as Category[]),
    getProducts(query).catch(() => null),
  ]);
  const current = categories.find((c) => c.slug === query.category);

  const title = query.q ? `Results for “${query.q}”` : current ? current.name : "All products";

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="space-y-6" aria-label="Filters">
        <CategoryList categories={categories} query={query} />
        <PriceFilter query={query} />
      </aside>

      <section aria-labelledby="results-heading">
        <div className="relative isolate mb-6 overflow-hidden rounded-2xl bg-brand-950 p-6 text-white sm:p-8">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={current?.image_url ?? "/images/hero.jpg"}
            alt=""
            className="absolute inset-0 -z-10 h-full w-full object-cover"
          />
          <div className="absolute inset-0 -z-10 bg-linear-to-r from-brand-950/90 to-brand-950/40" />
          <nav aria-label="Breadcrumb" className="mb-8 text-sm text-white/80">
            <Link href="/" className="hover:text-white">
              Home
            </Link>{" "}
            /{" "}
            <Link href="/shop" className="hover:text-white">
              Shop
            </Link>
            {current && <> / {current.name}</>}
          </nav>
          <h1 id="results-heading" className="text-4xl font-semibold">
            {title}
          </h1>
          {result && (
            <p className="mt-1 text-sm text-white/80">
              {result.total} {result.total === 1 ? "product" : "products"}
            </p>
          )}
        </div>
        <div className="mb-5 flex justify-end">
          <SortSelect value={query.sort ?? "newest"} />
        </div>

        {!result ? (
          <EmptyState title="We couldn't load products">Please check your connection and refresh the page.</EmptyState>
        ) : !result.items.length ? (
          <EmptyState
            title="No products found"
            action={
              <Link href="/shop" className="btn-primary">
                Clear filters
              </Link>
            }
          >
            Try a different word or remove a filter.
          </EmptyState>
        ) : (
          <>
            <ProductGrid products={result.items} />
            <Pagination query={query} page={result.page} pages={result.pages} />
          </>
        )}
      </section>
    </div>
  );
}

function CategoryList({ categories, query }: { categories: Category[]; query: ProductQuery }) {
  const top = categories.filter((c) => !c.parent_id);
  const children = (id: string) => categories.filter((c) => c.parent_id === id);
  const item = (c: Category | null, depth = 0) => {
    const active = (c?.slug ?? undefined) === query.category;
    return (
      <li key={c?.id ?? "all"}>
        <Link
          href={shopHref(query, { category: c?.slug })}
          aria-current={active ? "page" : undefined}
          className={`block whitespace-nowrap rounded-lg px-3 py-2 text-sm lg:whitespace-normal ${depth ? "pl-6" : ""} ${
            active ? "bg-brand-50 font-semibold text-brand-800" : "text-slate-700 hover:bg-slate-50"
          }`}
        >
          {c ? c.name : "All products"}
        </Link>
      </li>
    );
  };
  return (
    <div className="card p-3">
      <h2 className="px-3 pb-2 pt-1 text-xs font-bold uppercase tracking-wide text-slate-500">Categories</h2>
      {/* Horizontal chips on phones, a list on large screens */}
      <ul className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
        {item(null)}
        {top.flatMap((c) => [item(c), ...children(c.id).map((ch) => item(ch, 1))])}
      </ul>
    </div>
  );
}

function PriceFilter({ query }: { query: ProductQuery }) {
  // A plain GET form keeps the other filters through hidden fields
  return (
    <form action="/shop" className="card space-y-3 p-4">
      <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Price (₦)</h2>
      {query.q && <input type="hidden" name="q" value={query.q} />}
      {query.category && <input type="hidden" name="category" value={query.category} />}
      {query.sort && query.sort !== "newest" && <input type="hidden" name="sort" value={query.sort} />}
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor="min_price">
          Minimum price
        </label>
        <input
          id="min_price"
          name="min_price"
          inputMode="numeric"
          pattern="[0-9]*"
          placeholder="Min"
          defaultValue={query.min_price}
          className="input"
        />
        <span className="text-slate-400">–</span>
        <label className="sr-only" htmlFor="max_price">
          Maximum price
        </label>
        <input
          id="max_price"
          name="max_price"
          inputMode="numeric"
          pattern="[0-9]*"
          placeholder="Max"
          defaultValue={query.max_price}
          className="input"
        />
      </div>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          name="in_stock"
          value="1"
          defaultChecked={query.in_stock_only}
          className="h-4 w-4 accent-brand-600"
        />
        In stock only
      </label>
      <button className="btn-secondary w-full">Apply</button>
    </form>
  );
}

function Pagination({ query, page, pages }: { query: ProductQuery; page: number; pages: number }) {
  if (pages <= 1) return null;
  const href = (p: number) => shopHref(query, { page: p > 1 ? String(p) : undefined });
  return (
    <nav className="mt-8 flex items-center justify-center gap-2" aria-label="Pages">
      {page > 1 && (
        <Link href={href(page - 1)} className="btn-secondary">
          Previous
        </Link>
      )}
      <span className="px-3 text-sm text-slate-600">
        Page {page} of {pages}
      </span>
      {page < pages && (
        <Link href={href(page + 1)} className="btn-secondary">
          Next
        </Link>
      )}
    </nav>
  );
}
