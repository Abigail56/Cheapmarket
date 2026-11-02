"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/providers/auth";
import { useCart } from "@/providers/cart";

import { CartIcon, CloseIcon, MenuIcon, SearchIcon, UserIcon } from "./icons";
import { Logo } from "./ui";

function SearchForm({ className = "" }: { className?: string }) {
  // A plain GET form: works before JavaScript loads and gives shareable /shop?q= links
  return (
    <form action="/shop" role="search" className={`relative ${className}`}>
      <label htmlFor="site-search" className="sr-only">
        Search products
      </label>
      <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
      <input
        id="site-search"
        name="q"
        type="search"
        placeholder="Search rice, tomatoes, chicken…"
        className="input pl-10"
        maxLength={100}
      />
    </form>
  );
}

export function Header() {
  const { user, ready } = useAuth();
  const { cart } = useCart();
  const [menuOpen, setMenuOpen] = useState(false);

  const firstName = user?.full_name.split(" ")[0];

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/95 backdrop-blur">
      <div className="container-page flex h-16 items-center gap-4">
        <button
          type="button"
          className="btn-ghost -ml-2 p-2 md:hidden"
          onClick={() => setMenuOpen((o) => !o)}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
        >
          {menuOpen ? <CloseIcon /> : <MenuIcon />}
        </button>
        <Logo />

        <nav className="ml-4 hidden items-center gap-1 md:flex" aria-label="Main">
          <Link href="/shop" className="btn-ghost px-3">
            Shop
          </Link>
          <Link href="/shop?sort=price_asc" className="btn-ghost px-3">
            Lowest prices
          </Link>
          <Link href="/track" className="btn-ghost px-3">
            Track an order
          </Link>
        </nav>

        <SearchForm className="mx-auto hidden max-w-md flex-1 md:block" />

        <div className="ml-auto flex items-center gap-1 md:ml-0">
          <Link
            href={user ? "/account" : "/login"}
            className="btn-ghost px-2.5"
            aria-label={user ? "Your account" : "Sign in"}
          >
            <UserIcon />
            <span className="hidden lg:inline">{!ready ? "Account" : user ? `Hi, ${firstName}` : "Sign in"}</span>
          </Link>
          <Link href="/cart" className="btn-ghost relative px-2.5" aria-label={`Cart, ${cart.item_count} items`}>
            <CartIcon />
            <span className="hidden lg:inline">Cart</span>
            {cart.item_count > 0 && (
              <span className="absolute -right-0.5 -top-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-deal-600 px-1 text-[11px] font-bold text-white">
                {cart.item_count > 99 ? "99+" : cart.item_count}
              </span>
            )}
          </Link>
        </div>
      </div>

      <div className="container-page pb-3 md:hidden">
        <SearchForm />
      </div>

      {menuOpen && (
        <nav className="border-t border-slate-200 bg-white md:hidden" aria-label="Mobile">
          <div className="container-page flex flex-col py-2">
            {[
              ["/shop", "Shop all"],
              ["/shop?sort=price_asc", "Lowest prices"],
              ["/track", "Track an order"],
              [user ? "/account" : "/login", user ? "My account" : "Sign in"],
              ...(user ? [["/account/orders", "My orders"]] : [["/register", "Create an account"]]),
            ].map(([href, label]) => (
              <Link
                key={href}
                href={href}
                onClick={() => setMenuOpen(false)}
                className="rounded-lg px-2 py-3 text-sm font-medium hover:bg-slate-50">
                {label}
              </Link>
            ))}
          </div>
        </nav>
      )}
    </header>
  );
}
