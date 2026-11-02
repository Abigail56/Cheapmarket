import Link from "next/link";

import { money } from "@/lib/format";
import type { Product } from "@/lib/types";

import { AddToCart } from "./add-to-cart";
import { ProductImage } from "./product-image";

export function ProductCard({ product }: { product: Product }) {
  return (
    <article className="card group flex flex-col overflow-hidden transition duration-300 hover:-translate-y-1 hover:shadow-xl">
      <Link href={`/products/${product.slug}`} className="relative block overflow-hidden">
        <ProductImage src={product.image_url} alt={product.name} className="block aspect-[4/3] w-full transition duration-500 group-hover:scale-105" />
        {product.discount_percent ? (
          <span className="absolute left-2 top-2 rounded bg-deal-600 px-1.5 py-0.5 text-xs font-medium text-white">
            -{product.discount_percent}%
          </span>
        ) : null}
      </Link>
      <div className="flex flex-1 flex-col gap-2 p-3 sm:p-4">
        <p className="text-xs text-slate-500">{product.category.name}</p>
        <h3 className="line-clamp-2 text-sm font-semibold text-slate-900 sm:text-base">
          <Link href={`/products/${product.slug}`} className="hover:text-brand-700">
            {product.name}
          </Link>
        </h3>
        <p className="text-xs text-slate-500">{product.unit}</p>
        <div className="mt-auto flex flex-wrap items-end justify-between gap-2 pt-1">
          <div>
            <p className="text-base font-bold text-slate-900 sm:text-lg">{money(product.price)}</p>
            {product.compare_at_price ? (
              <p className="text-xs text-slate-400 line-through">{money(product.compare_at_price)}</p>
            ) : null}
          </div>
          <AddToCart productId={product.id} name={product.name} inStock={product.in_stock} />
        </div>
      </div>
    </article>
  );
}

export function ProductGrid({ products }: { products: Product[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-5 md:grid-cols-3 lg:grid-cols-4">
      {products.map((p) => (
        <ProductCard key={p.id} product={p} />
      ))}
    </div>
  );
}

export function ProductGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-5 md:grid-cols-3 lg:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card overflow-hidden">
          <div className="aspect-square animate-pulse bg-slate-100" />
          <div className="space-y-2 p-4">
            <div className="h-3 w-1/3 animate-pulse rounded bg-slate-100" />
            <div className="h-4 w-3/4 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-1/2 animate-pulse rounded bg-slate-100" />
          </div>
        </div>
      ))}
    </div>
  );
}
