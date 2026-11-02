# Cheapmarketdeal shop

The customer website: browse and search products, cart, checkout (card, bank transfer or pay on delivery), order tracking, and customer accounts. Built with Next.js 16 (App Router, Cache Components) and Tailwind CSS 4. It talks to the API in `../Backend`.

## Run it locally

```bash
# 1. the API (from ../Backend): docker compose up -d
# 2. the shop
cp .env.example .env.local      # set NEXT_PUBLIC_API_URL to your API, e.g. http://localhost:8010
npm install
npm run dev                     # http://localhost:3020
```

The API must allow the shop's address: put `http://localhost:3020` in the backend's `CORS_ORIGINS` and set `FRONTEND_URL=http://localhost:3020` (card payments return there). Port 3020 is used because 3000 is often taken.

To try it on a phone on the same Wi-Fi, open `http://<this computer's IP>:3020`. With `ENVIRONMENT=local` the API accepts that address, and the shop finds the API at the same IP (it must be reachable there on port 8010).

Without payment keys (and `ENVIRONMENT=local`), card checkout goes to a **test payment page** (`/mock-pay`) with a "Simulate successful payment" button. In production the API never sends anyone there, and the button's endpoint answers 404.

## Pages

| Page | What it does |
|---|---|
| `/` | Home: categories, this week's picks, newest products, delivery zones |
| `/shop` | All products with search (`?q=`), category, price, in-stock filter, sorting, pages |
| `/products/[slug]` | Product details and related products |
| `/cart` | Change quantities, remove items |
| `/checkout` | Contact details, saved or new address, delivery zone, coupon, live price from the server, payment method |
| `/orders/[number]` | Order status, items, totals, bank transfer details, pay now, cancel. Guests confirm with their phone number |
| `/orders/[number]/payment-complete` | Where Paystack/Flutterwave send the customer back; confirms the payment |
| `/track` | Look up any order with its number + phone |
| `/login`, `/register`, `/forgot-password`, `/reset-password` | Accounts (plus "Continue with Google" when the API has `GOOGLE_CLIENT_ID`) |
| `/account`, `/account/orders`, `/account/addresses` | Profile, phone verification, password, order history, saved addresses |

## How it works

- **Catalogue pages render on the server** (good for Google and fast first load); the API already caches the catalogue in Redis. Cart, checkout and account pages run in the browser.
- **Guests** get a cart session id from the API, kept in the browser. After signing in, the guest cart is merged into the account.
- **Login tokens** are kept in the browser and refreshed automatically when they expire.
- **Prices are never trusted from the browser**: the checkout total shown comes from the API's quote, and the API recalculates everything when the order is placed.

## Checks

```bash
npm run lint
npx next typegen && npx tsc --noEmit
npm run build
```

CI runs these and builds the Docker image on every push. In production the shop runs as the `web` service in `../Backend/docker-compose.prod.yml`, served by Caddy at `SHOP_DOMAIN`.
