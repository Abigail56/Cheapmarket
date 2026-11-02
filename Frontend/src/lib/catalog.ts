// Server-side reads of the public catalogue (rendered on the server so search engines see
// products). The API caches the catalogue in Redis, so these fetch fresh on each request.
import { SERVER_API_URL } from "./config";
import type { Category, Page, Product, ProductSort, Zone } from "./types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${SERVER_API_URL}/api/v1${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status} for ${path}`);
  return (await res.json()) as T;
}

export const getCategories = () => get<Category[]>("/categories");

export const getZones = () => get<Zone[]>("/delivery-zones");

export async function getProduct(slug: string): Promise<Product | null> {
  const res = await fetch(`${SERVER_API_URL}/api/v1/products/${encodeURIComponent(slug)}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${res.status} for product ${slug}`);
  return (await res.json()) as Product;
}

export interface ProductQuery {
  category?: string;
  q?: string;
  sort?: ProductSort;
  min_price?: string;
  max_price?: string;
  in_stock_only?: boolean;
  featured?: boolean;
  page?: number;
  size?: number;
}

export function getProducts(query: ProductQuery = {}) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== "" && v !== false) params.set(k, String(v));
  }
  const qs = params.toString();
  return get<Page<Product>>(`/products${qs ? `?${qs}` : ""}`);
}
