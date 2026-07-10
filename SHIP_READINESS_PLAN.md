# Ship-Readiness Plan

Compiled 2026-07-09 from a full-application audit: manual review of both Shopify clients,
schema validation of all 15 GraphQL operations against the Shopify dev MCP (API 2026-04),
official Shopify docs cross-checks, and parallel audits of API usage, security, and architecture.

Status legend: `[ ]` todo · `[x]` done · `[~]` partially done / needs infra decision

---

## Phase 1 — Critical Shopify API fixes (URGENT: pinned 2025-04 is retired; its 2025-07 fallback retires 2026-07-16)

- [x] **1.1 Fix broken `FulfillmentEvent.address2` query** — `backend/enhanced_shopify_client.py:392`.
      Field does not exist in any API version; `get_fulfillment_by_id()` always errors and returns `None`.
- [x] **1.2 Bump API version to 2026-04 everywhere**
  - [x] `backend/shopify_client.py:15` default `2025-04` → `2026-04`
  - [x] `backend/enhanced_shopify_client.py:15` hardcodes `2025-04` — must read `SHOPIFY_API_VERSION` env like the main client
  - [x] `.env`, `.env.example`, `docker-compose.prod.yml:47`, `docker-compose.postgres.yml:55,89,125` defaults
  - [x] Log a warning when the `X-Shopify-API-Version` response header differs from the requested version (Shopify's official out-of-date signal)
- [x] **1.3 Migrate `inventorySetQuantities`** — `backend/shopify_client.py:3433-3531`.
      `ignoreCompareQuantity` is removed in 2026-04; replace with explicit `compareQuantity/changeFromQuantity: null` per quantity entry (validate exact field via MCP before writing).
- [x] **1.4 Harden order-search queries** — `backend/shopify_client.py:1978,2040-2046`.
  - [x] Quote interpolated values (`name:"..."`, `email:"..."`) and validate inputs (query injection / `#` in order names)
  - [x] Remove unsupported leading-wildcard `phone:*digits*` search term
  - [x] `get_order_fraud_data`: verify `node.name == order_name` after `orders(first:1, query:...)` fetch (can silently analyze the wrong order)
- [x] **1.5 Re-validate all changed GraphQL operations via Shopify MCP at 2026-04**
- [ ] **1.6 (follow-up) Migrate deprecated Customer fields** — `Customer.email` → `defaultEmailAddress.emailAddress`,
      `Customer.phone` → `defaultPhoneNumber.phoneNumber`, `Customer.addresses` → `addressesV2`.
      Still functional in 2026-04 (deprecation warnings only); shape change ripples into fraud_service/rule_engine — do as its own change.

## Phase 2 — Security blockers

- [x] **2.1 Secrets hygiene**
  - [x] Delete `.env.backup_sqlite` (contains live secrets, NOT git-ignored — one `git add -A` from a leak)
  - [x] Broaden `.gitignore`: `.env*` except `.env.example`; add `*.backup`, backups/
- [x] **2.2 Remove well-known secret fallbacks from compose files**
  - [x] `docker-compose.prod.yml:41-44` (`SECRET_KEY`/`ADMIN_SECRET_KEY`/`JWT_SECRET_KEY` fallbacks → JWT forgery), Postgres `changeme` default, `--reload` in prod, no mem limits — deprecate this file in favor of `docker-compose.postgres.prod.yml`
  - [x] `docker-compose.yml:66,86` literal placeholder `SECRET_KEY` for worker/scheduler → use `${SECRET_KEY:?must be set}` form
  - [x] Add missing `ENCRYPTION_KEY` wherever api/worker/scheduler env omits it
- [x] **2.3 Apply rate limits to `/auth/login`, `/auth/register`, `/auth/refresh`** — `backend/routers/auth.py` imports `AUTH_LIMIT`/`REGISTER_LIMIT` but never applies them
- [x] **2.4 Enforce `User.is_active` in `get_current_user`** — `backend/auth.py:108` (deactivated users keep access until JWT expiry)
- [x] **2.5 Redis/Postgres exposure** — bound to 127.0.0.1 in all compose files (was 0.0.0.0). Redis password still recommended as follow-up (needs coordinated REDIS_URL change in .env on the prod host)
- [~] **2.6 TLS** — active nginx config listens on 80 only (443 block commented out). Needs cert/domain decision; `install-ssl-production.sh` exists
- [x] **2.7 Forced first-login password change or generated password for default `admin`/`admin`** — `backend/init_admin.py:42-64`
- [x] **2.8 Refresh-token revocation + server-side logout** (stolen refresh token currently valid full 7 days)
- [x] **2.9 Add CSP + HSTS headers in nginx** (JWT lives in localStorage — CSP is the mitigation)

## Phase 3 — Reliability (Celery + throttling)

- [x] **3.1 Celery retry policy** — all 11 tasks have no `autoretry_for`/`retry_backoff`; add with jitter for transient Shopify/DB/Redis errors
- [x] **3.2 `task_acks_late=True` + `task_reject_on_worker_lost=True`** — safe given `ProcessedOrder` unique constraint + Redis locks; without it a worker OOM silently loses work
- [x] **3.3 Proper THROTTLED handling in `_make_graphql_request`** — detect `errors[].extensions.code == "THROTTLED"`, wait based on `throttleStatus.restoreRate` / `Retry-After` header instead of blind 1/2/4s; remove dead per-instance "auto-optimization" state
- [x] **3.4 Per-store single-flight lock** — `store.last_sync` written only post-completion (`tasks.py:845,1800`) while beat fires every minute → concurrent duplicate store syncs
- [x] **3.5 Throttle handling + page delay in the main order loop (`tasks.py:904-1081`) and bulk fraud loop (`tasks.py:2196`)**; don't silently truncate on THROTTLED (`tasks.py:1742`)
- [x] **3.6 Guard unchecked `orders_data["edges"]` / `["pageInfo"]` index access** — `tasks.py:914,1077`

## Phase 4 — OAuth2 + webhooks

- [x] **4.1 OAuth authorization-code grant (standalone app, offline access token)**
  - [x] Install endpoint: validate `*.myshopify.com` domain, `state` nonce in Redis, redirect to `/admin/oauth/authorize`
  - [x] Callback: verify `state` + HMAC (constant-time), exchange code at `/admin/oauth/access_token`, prefer expiring offline tokens (`expiring=1`, store refresh token)
  - [x] DB: add `auth_method`, `granted_scopes`, `refresh_token` (encrypted), `token_expires_at`, `installed_at` to `shopify_stores`
  - [x] Keep manual admin-token path as a second connection method (also: OAuth `read_orders` only sees 60 days of orders; fraud history needs `read_all_orders` approval — manual tokens don't)
  - [x] On Shopify 401 → flip store to "reauthorize" state surfaced in UI
- [x] **4.2 Webhooks**
  - [x] Webhook receiver with `X-Shopify-Hmac-Sha256` verification (401 on failure) — nginx `app-locations.conf` proxy block exists but has no backend handler
  - [x] `app/uninstalled` → disconnect store, purge token
  - [x] `orders/create` / `orders/updated` to replace/reduce 1-minute polling (Shopify-recommended OMS pattern), keep polling as reconciliation
  - [x] GDPR compliance webhooks (`customers/data_request`, `customers/redact`, `shop/redact`) if App Store distribution

## Phase 5 — Data correctness hardening

- [x] **5.1 Nested-connection truncation** — `lineItems(first:20)` in sync queries silently truncates orders >20 items and `rule_engine.py:283-285` then prefers the undercounted calculated weight; detect `pageInfo.hasNextPage` on nested connections and re-fetch via `get_order_by_id` (first:100), or paginate
- [x] **5.2 Null-shape safety** — `shippingAddress: null` (digital orders), `customer: null` (guest checkout), `variant: null` (deleted products), null `province` crash `rule_engine.py:290-301,231-232`
- [~] **5.3 Money as Decimal** — verified all flagged divisions are already zero-guarded; fraud_service already uses Decimal. rule_engine keeps float for threshold comparisons (documented decision — thresholds are user-entered floats; no arithmetic accumulates error)
- [x] **5.4 SKU/barcode conflation** — `shopify_client.py:3217` filters `sku:"{barcode}"` but matches `variant.barcode` → stores where SKU ≠ barcode always get 0
- [ ] **5.5 `updated_at` reconcile pass** — NEEDS DESIGN: re-fetched orders would be skipped by the ProcessedOrder idempotency check; requires a reprocess-on-update policy decision first. orders/updated webhook (4.2) now covers connected OAuth stores
- [~] **5.6 Shared httpx client** — sync.py now uses public `execute_graphql()`; per-request AsyncClient kept (clients are created per Celery task with fresh event loops — pooling across loops would break); revisit if API latency matters

## Phase 6 — Hygiene, observability, CI

- [x] **6.0 Unified installer** — `install.sh`: Install (prompts for server address/Shopify OAuth keys/admin password, auto-generates SECRET_KEY/ADMIN_SECRET_KEY/ENCRYPTION_KEY/DB password — no manual .env editing), Update from GitHub (backup of .env + pg_dump → git pull --ff-only → rebuild → migrations → docker image/build-cache prune), Backup, Remove (optional volume deletion with typed confirmation). Legacy update*.sh marked superseded.

- [x] **6.1 Repo cleanup** — move ~96 `debug_/test_/check_/fix_/diagnose_` scripts to `scripts/` (excluded from Docker build); delete `tasks.py.backup`, stray `.db` files, `backups/` tarball; move status `.md` reports to `docs/`
- [x] **6.2 `.dockerignore`** covering scripts, docs, env files, db files
- [ ] **6.3 Error tracking (Sentry) + structured logging**; replace remaining `print()` in `tasks.py`
- [ ] **6.4 Indexes on FK/hot columns** — `user_id`/`store_id` on `OrderLog`, `FraudAnalysis`, etc.
- [ ] **6.5 Adopt Alembic** (already in requirements, unused; 20 hand-written migration scripts today)
- [ ] **6.6 CI** — run `backend/tests/` pytest suite + frontend vitest
- [ ] **6.7 Frontend** — axios timeout, token storage review, split large components

---

## Reference: MCP validation results (2026-04)

12/15 operations valid. Failures/warnings:
- `FulfillmentEvent.address2` — does not exist (any version) → **live bug** (1.1)
- `InventorySetQuantitiesInput.ignoreCompareQuantity` — removed in 2026-04 (1.3)
- Deprecations: `Customer.email`, `Customer.phone`, `Customer.addresses` (1.6)

Required scopes across all operations: `read_orders`, `write_orders` (tagging), `read_customers`,
`read_products`, `read_inventory`, `write_inventory`, `read_locations`,
`read_assigned_fulfillment_orders`, `read/write_merchant_managed_fulfillment_orders`,
`read/write_third_party_fulfillment_orders`.
