# Cheapmarketdeal API

FastAPI · SQLModel · PostgreSQL · Redis · pydantic-settings · Alembic

## Quick start

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste as SECRET_KEY in .env
mkdir -p backups media                            # create as you, so the containers can write there

docker compose up --build                         # Postgres, Redis, migrations, API, worker, backups
docker compose exec api python -m scripts.seed    # sample products, zones, coupon, admin user
```

- Interactive docs: http://localhost:8000/docs  (click **Authorize** and log in)
- Health check: http://localhost:8000/health
- Seeded admin: `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env` (**change them**). Demo rider (local only): `rider@example.com` / `Rider12345!`
- SMS/emails (order updates, reset codes) appear in the worker log until you configure a provider: `docker compose logs -f worker`

## Services

| Service | What it does |
|---|---|
| `api` | The HTTP API (`uvicorn`, 2 workers in the image; `WEB_CONCURRENCY` to change) |
| `worker` | `python -m app.worker`: sends queued SMS/emails (with retries) and every 5 min re-checks card payments whose webhook never arrived |
| `backup` | `pg_dump` once a day into `./backups`, keeps 14 days (see [Backups](#backups)) |
| `db`, `redis` | PostgreSQL 16, Redis 7 |

## Tests

Tests use real PostgreSQL + Redis (a separate `cmd_test` database and Redis DB 15).

```bash
docker compose up -d db redis
docker compose exec db psql -U $POSTGRES_USER -c "CREATE DATABASE cmd_test;"
uv sync && uv run pytest        # 209 tests
```

CI (`.github/workflows/ci.yml`) runs lint, checks migrations apply and match the models, runs the tests and builds the Docker image on every push and pull request.

## Layout

`api/` (HTTP) → `services/` (business rules) → `repositories/` (queries) → `models/` (tables). `schemas/` = request/response models, built on the shared `*Base` classes in `models/`. `worker.py` = background jobs.

## API overview (all under `/api/v1`)

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register` (returns tokens) `· /auth/login · /auth/refresh · /auth/logout · /auth/password/forgot · /auth/password/reset` |
| Account | `GET/PATCH /users/me · POST /users/me/password · POST /users/me/phone/verify · /phone/verify/confirm · CRUD /users/me/addresses` |
| Catalogue (public, cached) | `GET /categories · /products?category&q&min_price&max_price&sort&page · /products/{slug} · /delivery-zones` |
| Cart (guest or user) | `GET /cart · POST /cart/items · PUT/DELETE /cart/items/{product_id} · DELETE /cart · POST /cart/merge` |
| Checkout | `POST /checkout/quote · POST /orders · GET /orders · GET /orders/{no} · POST /orders/track · POST /orders/{no}/cancel` |
| Payments | `POST /payments/initialize · GET /payments/verify/{ref} · POST /payments/webhook/paystack · /webhook/flutterwave` |
| Rider | `GET /rider/deliveries · PATCH /rider/deliveries/{id}` |
| Notification bell | `GET /notifications · POST /notifications/{id}/read · POST /notifications/read-all` |
| Admin | `/admin/products · /categories · /orders · /zones · /coupons · /users · /dashboard · /audit-logs · POST /admin/uploads/images` |

**Guests:** the first `POST /cart/items` returns a `session_id` (also in the `X-Cart-Session` response header). Send it back as the `X-Cart-Session` header on cart and checkout calls. After login, call `POST /cart/merge`.

**Continue with Google:** set `GOOGLE_CLIENT_ID` (Google Cloud Console → APIs & Services → Credentials → OAuth client ID → Web application; add each address the pages are opened from under *Authorized JavaScript origins*; no client secret needed). The server verifies Google's signed ID token itself (Google's keys, our client ID, not expired, email verified). `POST /auth/google {id_token, create_account}`: signs in the account with that Google identity, links an existing account with the same verified email, or creates a **customer** when `create_account` is true (for the shop frontend). The rider app and dashboard send `create_account: false`, so they only sign existing riders/admins in. Riders can also **apply with Google** (name and verified email from Google; they still add phone, vehicle and ID, and still need approval). Google never grants admin or rider roles. Buttons only appear once the client ID is set.

**Login:** `POST /auth/login {"email", "password"}` returns `{access_token, refresh_token}`. In Swagger: call `/auth/login`, copy the `access_token`, click **Authorize** and paste it (no `Bearer ` prefix). Admin endpoints accept only an admin's token (others get 403). Phone numbers are for SMS (order updates, phone verification), not for logging in or resetting passwords.

**Accounts:** `/auth/register` always creates a **customer** (any `role` sent is ignored) and returns `{user, access_token, refresh_token}`. Admin and rider accounts can only be created by an existing admin with `POST /admin/users` (`role` defaults to `admin`). The first admin comes from `scripts.seed`.

**Riders join two ways:** an admin creates them (`POST /admin/users` with `"role": "rider"`), or they **apply in the rider app** ("Apply to ride with us": name, phone, email, password, vehicle, plate, area, plus their **ID**: type, number, a photo of the front (required) and back (optional), and a face photo). An applicant's account exists but can't sign in, see or be offered deliveries until an admin approves it. Signing in meanwhile says the application is being reviewed (only after the right password). The dashboard plays the siren and lists applications with **Approve** / **Reject**; the applicant is texted the decision (a rejection includes your reason). **Is the ID real?** Each application is checked in the background (the worker) and the dashboard shows the result: ✅ verified, ⚠️ needs a close look, ❌ ID not found, 🔎 check by hand, or ⚠️ check didn't run (with **Check again**). Always on, free: the number must look right for its type (a NIN is exactly 11 digits), and an ID number already on another application is flagged; either one means "needs a close look". With `ID_VERIFY_PROVIDER=dojah` (a licensed verification company; paid per check, ~₦50-₦150), a **NIN** is looked up with NIMC through Dojah, the **selfie is face-matched** against the photo NIMC holds (`ID_FACE_MATCH_THRESHOLD`, default 90), and the registered name is compared with the typed one (`ID_NAME_MATCH_THRESHOLD`, default 80; order and tone marks don't matter). Driver's licences, voter's cards and passports aren't covered by Dojah's current docs, so they're marked for a manual check. Only the registered name and the scores are stored, never the government photo, date of birth or phone the provider returns. Approving someone who isn't verified asks for confirmation, and the check result is recorded with the approval in the audit log.

**ID documents are private:** they're stored in the database (table `rider_documents`), never in the public `/media` folder, so they have no public link. Only admins can open them (`GET /admin/rider-applications/{id}/documents/{doc_id}`, never cached), and **every view is recorded in the audit log**. Every uploaded photo (ID documents, delivery proof, product images) is **rebuilt from its pixels on the server** (Pillow): all hidden metadata is removed (GPS location, camera serial, timestamps), sideways phone photos are turned upright, damaged or fake images are refused, and oversized "decompression bomb" images are blocked. This happens even when someone uploads straight to the API. They're deleted if the application or account is deleted. Note that database backups now contain ID images: keep `./backups` as private as the database. API: `POST /auth/rider-signup` (multipart), `GET /admin/rider-applications?status=pending`, `POST /admin/rider-applications/{id}/approve` and `/reject`. Decisions are in the audit log.

**Forgotten password:** `POST /auth/password/forgot {email}` emails a 6-digit code. `POST /auth/password/reset {email, code, new_password}` sets the new password and **signs out every device**. Codes last 15 minutes, work once, and die after 5 wrong guesses. The forgot endpoint answers the same whether or not the account exists.

**Images:** upload with `POST /admin/uploads/images` (multipart `file`, `?folder=products|categories`; JPEG/PNG/WebP up to 5 MB, type checked from the file's bytes), then put the returned `url` in the product's or category's `image_url`.

## Order lifecycle

`pending → confirmed → packed → out_for_delivery → delivered` (any step before delivery can go to `cancelled`; cancelling restores stock).

- **COD:** can be confirmed immediately; marked paid automatically on delivery.
- **Card:** confirmed automatically when the gateway webhook arrives (amount is verified). If the webhook never comes, the worker asks the gateway after 5 minutes; payments still pending after 48 hours are marked failed (a late webhook can still confirm them).
- **Bank transfer:** admin calls `POST /admin/orders/{no}/mark-paid` after seeing the money.

The customer gets an SMS (and an email, if they gave one) when the order is placed, paid, confirmed, out for delivery, delivered or cancelled.

## Managing products without a developer

Admins sign in at `/dashboard` and open **Products & prices** to add or edit products, upload photos, set stock, and put items on sale. A discount is a percentage off the normal price, on one product, one category or the whole shop. A new discount replaces the old one (they never stack), and ending it restores the normal price. Each change is recorded in the audit log.

The **Categories** tab adds, renames and deletes categories (a category must be empty before it can be deleted), and **Delivery areas** sets each area's name, fee and free-delivery amount, and whether customers can choose it at checkout. **Coupons** creates discount codes and turns them on or off. **Riders** adds riders directly and suspends or restores them.

## New-order alarm

While `/dashboard` is open, a new order sets off a soft chime that repeats until someone taps **Stop alarm** or deals with the order. It also rings for orders placed while the page was closed or the connection was down. Browsers keep a page silent until it has been clicked once, so the page shows a reminder until then. A closed browser can't ring, so set `ADMIN_ALERT_PHONES` and/or `ADMIN_ALERT_EMAILS` to also send each new order by SMS or email.

## Riders, tracking and live dashboard

Three pages are served by the API itself (plain HTML + JS, no build step):

| Page | Who | What |
|---|---|---|
| `/rider/` | Riders | Installable phone app (PWA). Offers with a 5-minute accept countdown, address check with call button and GPS pin, navigation, live GPS, delivery photo + delivery code. Notification bell. Chimes on new offers. |
| `/track/<token>` | Customers | The link in their SMS (first when the order is placed, again when a rider accepts) and behind "Track your order live" in the shop. Status steps, the rider live on a map with ETA once on the way, call the rider, fix the landmark/pin until the rider leaves, and the delivery photo afterwards. |
| `/dashboard` | Admins | New orders (confirm, or mark a transfer paid), orders needing a rider (assign in one click), deliveries in progress, riders on a live map, delivery photos, event feed, notification bell. Chimes on new orders, declines, expired offers, wrong codes, failures and deliveries. |

**The journey:** admin assigns → rider accepts (or declines / doesn't answer in 5 min → back to the admin) → rider **confirms the address** (calls the customer, pins the door) → **Start journey** (order becomes *out for delivery*, customer gets the live link) → **I've arrived** (only within 300 m of the pin) → **Send delivery code** → rider takes a **photo**, the customer checks their items and types the code from their text on the rider's phone → *delivered* (COD marked paid). Every step updates the order, the customer's page and the dashboard live.

**Why the delivery code can't be faked:** the server makes it and texts it only to the customer; no API returns it (not even to the rider's app); only an HMAC bound to that one delivery is stored, so another order's code or a guess never matches; it expires in 10 minutes and dies after 5 wrong tries (each one alerts the admin); sending and using it both require the rider's GPS within `GEOFENCE_METERS` of the confirmed pin; a photo is required. If GPS is genuinely wrong at the door, an admin can **waive the location check** (recorded in the audit log). A rider using a GPS-spoofing app could still fake their position: the code (only the customer has it) and the photo are what prove the handover.

**Notification bell:** the dashboard and rider app each have a bell with an unread count. Every admin gets new orders, cancellations, rider answers, wrong codes, failed and completed deliveries, address changes and rider applications; a rider gets only their own offers, reassignments, cancellations and address changes. Lines are saved in the `notifications` table, so people see what they missed while away, and cleared after 30 days. To add one, add a line to `ADMIN_TEXT` or `RIDER_TEXT` in `services/inbox.py`. While the page is closed only riders get alerted (web push, below); admins see the bell when they come back.

**Calling the customer:** when a rider arrives, their app puts a "Call now" button at the top of the screen, and the customer also gets an automatic text. Calls use the rider's own phone. The dashboard shows the customer's number on every active delivery too, with a progress bar and the time of each step (offered, accepted, on the way, arrived, code sent) that updates by itself.

**If a delivery fails:** the rider reports it and the customer is told by text. The order goes back to **Need a rider** on the dashboard with the reason, where an admin can offer it to another rider (who starts fresh, with no waived location check carried over) or cancel it. The customer can correct their address in the meantime.

**Live updates** use server-sent events over Redis Streams (`GET /api/v1/admin/events`, `/rider/events`, `/track/<token>/events`). Pages also refresh every 30 s in case a connection drops. Browsers only allow sound after a tap, so the first tap on a page switches the alarm on. The speaker button in the header mutes it, and that choice is remembered on the device. Phone push alerts follow the phone's own settings.

**Alerts when the rider app is closed (web push):** new offers, customer address changes and cancellations are pushed to the rider's phone, even with the app closed (Android Chrome, desktop browsers, and iPhone with the app added to the home screen, iOS 16.4+). The rider taps **Turn on alerts** once. It uses standard Web Push with your own VAPID keys (no Firebase account): run `python -m scripts.vapid_keys`, put both lines in `.env`, and **keep them** (new keys break existing subscriptions). Payloads are encrypted so only the phone can read them, and the server only sends to the known browser push services (`PUSH_ALLOWED_HOSTS`). Riders still get an SMS for each offer too. Browsers don't let a website choose the sound of a push notification (the phone's own alert sound plays), so the alert vibrates hard and stays on screen until tapped. While the app is open it plays its own loud, sharp beep, and an unanswered offer beeps again every 12 seconds.

**Installing the rider app:** open `/rider/` on the phone and use "Install" / "Add to Home screen". Browsers only allow installing, GPS and the camera over **HTTPS** (or `localhost`), so put the API behind HTTPS before riders use it on real phones.

## Money & safety rules built in

- Totals, delivery fee and discounts are **always computed on the server**.
- Checkout locks product rows, so two people can't buy the last item.
- Orders store a snapshot of names/prices/address; later edits never change them.
- Webhooks: Paystack HMAC-SHA512 signature, Flutterwave hash + re-verification; payment amount must match the order total; replays are harmless.
- Refresh tokens rotate; logout revokes tokens (Redis); a password reset invalidates every token the user had.
- Login allows 5 attempts/min per IP, and locks an email/phone for 15 min after 5 failed passwords (`LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_SECONDS`).
- Every admin change (products, stock, categories, zones, coupons, users, order status/payment/rider) is written to `audit_logs` in the same transaction: who, what, old → new. Read it at `GET /admin/audit-logs`.

## Redis is used for

Catalogue caching (cleared when admins edit products or orders change stock), rate limiting and login lockout, revoked tokens, one-time codes, and the notification queue.
(Carts live in PostgreSQL so they survive restarts.)

**If Redis goes down** the shop keeps selling: the catalogue is served from PostgreSQL, rate limits and lockouts are skipped, and logged-out access tokens are honoured until they expire (max 30 min). Token refresh, password reset and notifications need Redis and fail until it's back.

## Logging & errors

Every request gets an id (`X-Request-ID` response header; send your own to trace a request end to end). It appears on every log line and in 500 error responses, so a customer's "error code" leads straight to the logs. Logs are JSON in staging/production, readable text locally. Set `SENTRY_DSN` to get errors (with tracebacks) in Sentry; no customer emails, phones or IPs are sent.

## Backups

The `backup` service writes `./backups/<db>_<timestamp>.dump` every `BACKUP_INTERVAL_SECONDS` (default daily) and deletes dumps older than `BACKUP_KEEP_DAYS` (default 14).

- **Copy `./backups` off the server** (e.g. `rclone` to S3/Backblaze/Google Drive on a cron). A backup on the same disk dies with the disk.
- **Restore** (replaces all data; asks you to type the database name):
  ```bash
  docker compose run --rm --entrypoint sh backup /restore.sh /backups/<file>.dump
  ```
- **Test a restore** every so often into a scratch database. A backup you've never restored is a hope, not a backup.

## Deploying (production)

`docker-compose.yml` is for development (live reload, your code folder mounted in, database and Redis on `127.0.0.1` only). On the server use **`docker-compose.prod.yml`**: it runs the API **and the customer shop** (`../Frontend`). The code is baked into the images, only **Caddy** is reachable from outside (ports 80/443, automatic HTTPS for the API at `DOMAIN` and the shop at `SHOP_DOMAIN`), Postgres/Redis/API/shop sit on an internal network, Redis needs a password, migrations run once before the API starts, and every service restarts by itself.

```bash
# on the server, with DNS A records for BOTH domains (e.g. api.yourdomain.com and
# yourdomain.com) pointing at it
git clone <this repo> && cd cheapmarketdeal-api/Backend   # the shop is built from ../Frontend
cp .env.production.example .env        # fill in every value marked REQUIRED
mkdir -p backups
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api python -m scripts.seed   # first admin
```

**The API refuses to start** with `ENVIRONMENT=production` if `SECRET_KEY` is weak, `DEBUG` is on, `PUBLIC_BASE_URL` isn't `https://`, or `REDIS_PASSWORD` is empty. The seed script refuses the default admin password.

Still yours to do (accounts and keys only you can get):

- Paystack/Flutterwave **live** keys in `.env`, and point the gateway webhook URLs at `https://<DOMAIN>/api/v1/payments/webhook/paystack` (and `/flutterwave`).
- A Termii account (`TERMII_API_KEY`, an approved `TERMII_SENDER_ID`) and an SMTP provider (`SMTP_*`). The API logs a warning at startup while production still uses `console`.
- A Sentry project for `SENTRY_DSN` (recommended).
- Images: `local` storage keeps them in the `media` Docker volume (back it up along with `./backups`). For several servers or a CDN, use `STORAGE_BACKEND=cloudinary`.
- The seed also adds the sample products, zones and the `WELCOME10` coupon: edit or remove them in the admin.
- Not built yet: automated refunds, WhatsApp messages.
