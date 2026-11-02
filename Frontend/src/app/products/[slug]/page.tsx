import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { AddToCart } from "@/components/add-to-cart";
import { ShieldIcon, TruckIcon } from "@/components/icons";
import { ProductGrid } from "@/components/product-card";
import { ProductImage } from "@/components/product-image";
import { getProduct, getProducts } from "@/lib/catalog";
import { money } from "@/lib/format";
import type { Product } from "@/lib/types";

export async function generateMetadata({ params }: PageProps<"/products/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const product = await getProduct(slug).catch(() => null);
  if (!product) return { title: "Product not found" };
  return {
    title: product.name,
    description:
      product.description?.slice(0, 160) || `Buy ${product.name} (${product.unit}) for ${money(product.price)}.`,
    openGraph: { images: product.image_url ? [product.image_url] : undefined },
  };
}

export default function ProductPage({ params }: PageProps<"/products/[slug]">) {
  return (
    <div className="container-page py-8">
      <Suspense fallback={<ProductSkeleton />}>
        <ProductDetails params={params} />
      </Suspense>
    </div>
  );
}

function ProductSkeleton() {
  return (
    <div className="grid gap-8 md:grid-cols-2">
      <div className="aspect-square animate-pulse rounded-3xl bg-slate-100" />
      <div className="space-y-4">
        <div className="h-4 w-24 animate-pulse rounded bg-slate-100" />
        <div className="h-8 w-3/4 animate-pulse rounded bg-slate-100" />
        <div className="h-8 w-32 animate-pulse rounded bg-slate-100" />
      </div>
    </div>
  );
}

async function ProductDetails({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const product = await getProduct(slug);
  if (!product) notFound();

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-5 text-sm text-slate-500">
        <Link href="/" className="hover:text-brand-700">
          Home
        </Link>{" "}
        /{" "}
        <Link href={`/shop?category=${product.category.slug}`} className="hover:text-brand-700">
          {product.category.name}
        </Link>{" "}
        / <span className="text-slate-700">{product.name}</span>
      </nav>

      <div className="grid gap-8 md:grid-cols-2 lg:gap-12">
        <div className="relative">
          <ProductImage
            src={product.image_url}
            alt={product.name}
            eager
            className="aspect-square w-full rounded-3xl border border-slate-200 bg-white"
          />
          {product.discount_percent ? (
            <span className="absolute left-3 top-3 rounded bg-deal-600 px-2 py-1 text-sm font-medium text-white">
              Save {product.discount_percent}%
            </span>
          ) : null}
        </div>

        <div className="flex flex-col">
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-700">{product.category.name}</p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-slate-900">{product.name}</h1>
          <p className="mt-1 text-slate-500">{product.unit}</p>

          <div className="mt-5 flex items-baseline gap-3">
            <span className="text-3xl font-extrabold text-slate-900">{money(product.price)}</span>
            {product.compare_at_price ? (
              <span className="text-lg text-slate-400 line-through">{money(product.compare_at_price)}</span>
            ) : null}
          </div>

          <p className={`mt-3 text-sm font-medium ${product.in_stock ? "text-brand-700" : "text-red-600"}`}>
            {product.in_stock ? "In stock" : "Out of stock right now"}
          </p>

          <div className="mt-6 max-w-sm">
            <AddToCart productId={product.id} name={product.name} inStock={product.in_stock} size="md" />
          </div>

          {product.description && (
            <div className="mt-8">
              <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">About this product</h2>
              <p className="mt-2 whitespace-pre-line leading-relaxed text-slate-700">{product.description}</p>
            </div>
          )}

          <ul className="mt-8 grid gap-3 text-sm text-slate-700 sm:grid-cols-2">
            <li className="flex items-start gap-3 rounded-xl bg-brand-50 p-3">
              <TruckIcon className="mt-0.5 shrink-0 text-brand-600" />
              Delivery fee depends on your zone and is shown before you pay.
            </li>
            <li className="flex items-start gap-3 rounded-xl bg-brand-50 p-3">
              <ShieldIcon className="mt-0.5 shrink-0 text-brand-600" />
              Pay on delivery, by bank transfer or by card.
            </li>
          </ul>
        </div>
      </div>

      <Suspense fallback={null}>
        <Related product={product} />
      </Suspense>
    </>
  );
}

async function Related({ product }: { product: Product }) {
  const page = await getProducts({ category: product.category.slug, size: 5, in_stock_only: true }).catch(() => null);
  const items = (page?.items ?? []).filter((p) => p.id !== product.id).slice(0, 4);
  if (!items.length) return null;
  return (
    <section className="mt-16" aria-labelledby="related-heading">
      <h2 id="related-heading" className="mb-5 text-2xl font-extrabold tracking-tight text-slate-900">
        More from {product.category.name}
      </h2>
      <ProductGrid products={items} />
    </section>
  );
}
