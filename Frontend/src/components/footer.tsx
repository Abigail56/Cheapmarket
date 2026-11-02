import Link from "next/link";

import { API_URL, SITE_NAME, SITE_TAGLINE, SUPPORT_EMAIL, SUPPORT_PHONE } from "@/lib/config";

import { Logo } from "./ui";

const COLUMNS = [
  {
    title: "Shop",
    links: [
      ["/shop", "All products"],
      ["/shop?sort=price_asc", "Lowest prices"],
      ["/cart", "Your cart"],
    ],
  },
  {
    title: "Your orders",
    links: [
      ["/track", "Track an order"],
      ["/account/orders", "Order history"],
      ["/account", "My account"],
    ],
  },
];

export function Footer() {
  return (
    <footer className="mt-20 bg-brand-950 text-white/75">
      <div className="container-page grid gap-10 py-14 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-4 lg:col-span-2">
          <Logo light />
          <p className="max-w-sm text-sm">{SITE_TAGLINE}.</p>
          {(SUPPORT_PHONE || SUPPORT_EMAIL) && (
            <p className="text-sm">
              Customer support:{" "}
              {SUPPORT_PHONE && (
                <a href={`tel:${SUPPORT_PHONE}`} className="text-white underline-offset-2 hover:underline">
                  {SUPPORT_PHONE}
                </a>
              )}
              {SUPPORT_PHONE && SUPPORT_EMAIL && " · "}
              {SUPPORT_EMAIL && (
                <a href={`mailto:${SUPPORT_EMAIL}`} className="text-white underline-offset-2 hover:underline">
                  {SUPPORT_EMAIL}
                </a>
              )}
            </p>
          )}
        </div>
        {COLUMNS.map((column) => (
          <div key={column.title}>
            <h2 className="mb-4 text-sm font-semibold text-white">{column.title}</h2>
            <ul className="space-y-2.5 text-sm">
              {column.links.map(([href, label]) => (
                <li key={href}>
                  <Link href={href} className="hover:text-white">
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-white/15">
        <div className="container-page flex flex-wrap justify-between gap-2 py-5 text-xs text-white/60">
          <p>© {SITE_NAME}. All prices are in Naira (₦).</p>
          <a href={`${API_URL}/rider/?apply=1`} className="hover:text-white">
            Become a rider
          </a>
        </div>
      </div>
    </footer>
  );
}
