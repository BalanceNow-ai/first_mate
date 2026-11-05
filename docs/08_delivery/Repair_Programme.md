# Helm / First Mate — Repair Programme: Plan, Closure Table and Checkpoint

This is the **canonical development plan and closure record** for the repair programme
started 2026-11-05 against `main@49877e2`. It supersedes the phase prompts in
`docs/07_code_reviews/` as the statement of what is actually implemented. Earlier
review approvals and the historical "115 passed" figure are **not** evidence for
anything recorded here; every status below cites fresh validation.

Status vocabulary (one per row):

- `RESOLVED_AND_VERIFIED` — implemented and proven by executed tests / journeys listed.
- `IMPLEMENTED_EXTERNAL_VALIDATION_PENDING` — code path complete and contract-tested
  locally; needs the named credential / partner to validate live. The production
  feature is disabled (or rejected) until configured.
- `BLOCKED` — a concrete unavailable dependency or authority boundary prevents it.
- `DEFERRED_FUTURE_SCOPE` — explicitly later rollout breadth only.

## 1. Plan (priority order)

1. **Foundation** — configuration with production validation, Supabase JWT verification
   (JWKS / server-only legacy secret), DB-held roles, rate limiting, money in integer
   minor units, full schema with Alembic revisions (baseline of the Phase-7 schema plus
   an upgrade with backfills), PostgreSQL-backed tests using real signed tokens.
2. **Contracts & identity** — one canonical field/unit contract; Flutter models parse real
   server payloads; configurable startup (API URL, Supabase, Stripe, monitoring);
   signup with/without confirmation, idempotent provisioning bound to the token subject,
   session restore/refresh/logout with cache clearing.
3. **Commerce** — central pricing, validated cart, stock reservation lifecycle with
   conditional updates, idempotent checkout and payment intents, signed webhooks with
   amount/currency/order binding, refunds, server-owned quotes, explicit local payment
   substitute (non-production only).
4. **Vessel intelligence** — boat OEM database, vessel equipment with provenance and
   verification, HIN decoding, central fitment (verified fit / verified mismatch /
   unknown), RAG ingestion + pgvector retrieval with citations, bounded tool-calling
   First Mate with deterministic offline substitute, structured product references,
   explicit-intent cart actions.
5. **Checklists, rewards, delivery, notifications** — tier inheritance and tailoring,
   fitment-based linking, stock-safe "add missing", export; points ledger, refund
   reversals, single-use discount entitlements, durable experience redemptions, crew
   invites; Helm Dash quotes/areas/dispatch/operator/location/payout records; courier
   adapters; notification outbox with local sinks; CMS adapter.
6. **Build & deployment** — declared runtime, buildable images, migrations sequencing,
   Celery tasks, Typesense sync, Compose networking, reverse proxy, health/readiness,
   failing-closed deploy script, backups/rollback, Flutter platform scaffolding.
7. **Verification** — full backend regression on PostgreSQL, Flutter analyze/test/build,
   clean-stack container journeys and browser journeys against the real local API.

## 2. Acceptance journeys

| # | Journey | Proof |
|---|---|---|
| J1 | Sign up (confirmation off and on), confirm, sign in, reload restores session, token refresh, sign out clears cached state; second account sees none of the first account's data | browser + API |
| J2 | Add vessel (HIN decode or manual), edit engine, view equipment/service history; other owner gets 404 | browser + API |
| J3 | Browse catalogue with vessel filter; sale price displayed equals cart line, order snapshot and provider charge | browser + API |
| J4 | Ask First Mate a maintenance question; answer cites an admitted source; compatible in-stock product shown; add to cart via explicit button. Change engine / revoke source → answer becomes unknown/limited | browser + API |
| J5 | Generate checklists, tick items, reload (persisted), add missing to cart twice (no duplication), export printable list | browser + API |
| J6 | Checkout courier / click-and-collect / Helm Dash with server quote; local test payment success; decline then retry; webhook duplicates/out-of-order; refund reverses points | API + browser |
| J7 | Two buyers race for the last item — exactly one reservation succeeds; expired reservation releases stock and restores the cart | API |
| J8 | Points awarded once per paid order; discount entitlement applied once; experience redemption creates fulfilment record | API + browser |
| J9 | Dispatcher assigns Helm Dash job; operator accepts and posts location; customer sees reported (not interpolated) position and status | API + browser |
| J10 | Clean install from empty DB, upgrade from Phase-7 schema with data, images build, API/worker/beat start and report readiness | containers |

## 3. Closure table

Status key: **RV** = RESOLVED_AND_VERIFIED · **EXT** = IMPLEMENTED_EXTERNAL_VALIDATION_PENDING
(production feature disabled/refused until configured) · **BLK** = BLOCKED · **DFS** =
DEFERRED_FUTURE_SCOPE. Proof references: `B:` backend pytest module (PostgreSQL +
pgvector, real signed tokens), `F:` Flutter test, `J:` journey script against the
containerised stack (§5), `M:` migration test.

### 3.1 Contracts and identity (brief §4)

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| F01 | Registration sent no `id`; server accepted arbitrary UUIDs | `POST /auth/provision` binds id+email to the verified token subject; idempotent; email bound to another subject → 409; Admin-API confirmation check when service key configured | B:test_auth (provision, smuggled id/role/email 422, 409, admin-API), J:api_journey | RV |
| F02 | `Supabase.instance` without `initialize()` | `main.dart` initialises before `runApp`, error screen on failure | F:startup tests, J:all browser journeys | RV |
| F03/F04 | Vessel `name` vs `nickname`; optional year | Canonical `nickname`, year required client+server; legacy `name` rejected 422 | B:test_vessels, F:contract fixtures, J:catalogue | RV |
| F05 | Product `stock_qty`/`weight_kg` | Canonical `stock_quantity`/`weight_grams`, money in `*_cents` | F:api_contract_test (server-produced fixtures) | RV |
| F06 | Chat read `response` | Typed `/ai/chat` contract (`message.content`, citations, products, actions) | F:engagement contract tests, J:engagement | RV |
| F07 | Hard-coded `localhost:8000` | `--dart-define` config; release builds refuse loopback unless `APP_ENV=development` | F:money_and_config_test, release build grep | RV |
| F08 | Configurable startup, no secrets in client | `AppConfig` (public values only); `/api/v1/config/public` for feature availability; secrets server-only | F:config tests, B:test_system (no secret in public config) | RV |
| F09 | Signup with/without confirmation, restore, refresh, logout, cross-account | Auth controller + interceptor (current Supabase token, single refresh, sign-out on failure), user-scoped providers rebuilt on user change | J:api_journey (GoTrue confirmation, refresh, logout revokes refresh token), J:foundation smoke + all browser journeys, F:auth tests | RV |
| F10 | Stripe initialisation / disabled state | Publishable key from public config; mobile PaymentSheet; web Payment Element (see C10); disabled → explicit state; Afterpay/Laybuy shown disabled with reason | F:checkout tests; no live Stripe keys | EXT (needs Stripe test/live keys + webhook endpoint secret) |
| F11 | Contract tests from actual payloads | 4 capture scripts drive the real stack (GoTrue sign-up, Mailpit) and store verbatim responses; Flutter parses them with production models | F:test/contract/*, fixtures under frontend/test/fixtures/api | RV |

### 3.2 Authority, ownership, privacy (brief §5)

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| S01 | Anon key used as HS256 secret | JWKS (ES256/RS256/EdDSA) or server-only legacy secret; alg pinned; exp/iat/iss/aud/sub required; anon/service-role/anonymous refused | B:test_auth (forged, expired, wrong aud/iss, alg none, anon-key signed, JWKS EC keys) | RV |
| S02 | Fail closed in production; no dev bypass | `Settings.validate_runtime()` at API/worker start; no unverified path exists | B:test_config (20 unsafe configurations refused) | RV |
| S03–S05 | Roles for catalogue, fulfilment, delivery ops; operator limits | Roles only in `users.role` (admin-audited, last-admin lock); `require_roles`; operators limited to own active jobs | B:test_auth, test_products_*, test_commerce_lifecycle, test_dispatch*, review regressions P4 | RV |
| S06 | Vessel ownership in AI context and compatibility; no private disclosure | All vessel lookups owner-scoped (404); vessel filters need token; AI tools bound server-side | B:test_integration_journeys (cross-owner across domains), test_ai_chat | RV |
| S07 | Sibling routes / tool paths | Independent review checked every router and AI tool | Review report (§5) | RV |
| S08 | Rate limits; bounded AI/tool/history | Redis fixed-window (memory in dev/test) on auth, mutations, search, AI minute+day; tool loop ≤ N; message/history/conversation bounds; int32/list bounds on every request | B:test_auth (429), test_ai_* (bounds, 429), review follow-ups | RV |
| S09 | Secrets/PII/provider errors out of responses and logs | Uniform error contract; generic 500; providers log error type only; notification log sink without PII | B:test_auth (no detail leak), test_notifications_outbox, test_ai_openai_provider | RV |

### 3.3 Commerce (brief §6)

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| C01 | Central money; sale price consistent to the charge | Integer cents; `pricing.effective_price_cents` used by cart, order snapshot, intent amount | B:test_commerce_checkout, test_integration_journeys, J:api_journey (total = cart + server shipping = intent amount) | RV |
| C02 | Validate quantity, active, aggregate stock everywhere incl. checklist bulk add | `cart_service` shared by cart API, checklists, AI actions | B:test_cart, test_checklists*, J:api_journey (add-missing twice) | RV |
| C03/C04 | Reservation lifecycle; no oversell; release once; recoverable carts | Conditional decrement reservations; consume/release/restock exactly once; expiry task (SKIP LOCKED) restores cart + entitlement | B:test_commerce_lifecycle (concurrent last item, expiry twice, cancel) | RV |
| C05 | Idempotent order and intent | `Idempotency-Key` checkout; intent reuse; per-request refund keys | B:test_commerce_checkout, test_payments_*, J:api_journey (double tap) | RV |
| C06/C07 | Authentic webhooks; identity/amount/currency/binding; duplicates/out-of-order | Signature always required; PaymentEvent dedupe; binding + amount + currency checks; deferral of refunds before success | B:test_payments_local, test_payments_stripe, J:api_journey (unsigned rejected) | RV (Stripe live: EXT) |
| C08 | Refunds and partial refunds | Cumulative refund deltas; restock only for full pre-dispatch refunds; points reversed proportionally (owed when spent); undispatched Helm Dash job cancelled | B:test_commerce_lifecycle, test_loyalty_ledger, review follow-ups | RV |
| C09 | Server-owned quotes; click & collect without courier pricing | `DeliveryQuote` bound to user/cart/type/destination/expiry/single use; DG restriction; operating areas | B:test_shipping_quotes, J:commerce journey | RV (courier rates use a configured rate card; carrier APIs EXT) |
| C10 | Card data with Stripe; pending/3DS/failed; client success never marks paid | Server-confirmed status only; local TEST MODE emits signed events through the real webhook path; Stripe PaymentSheet (mobile) and Payment Element (web) | J:commerce (decline → retry → paid), F:checkout tests | EXT (live Stripe keys) |
| C11 | Afterpay/Laybuy only if supported | Not offered; disabled with recorded reason (D7) | B:test_system, F:checkout | RV (as disabled) |
| C12 | Cart edit, checkout recovery, history, tracking entry points | Cart screen, orders list/detail, cancel/retry, Helm Dash tracking links | J:commerce, F:orders tests | RV |

### 3.4 Vessel intelligence (brief §7)

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| V01 | Boat model/year, OEM vs user equipment, provenance, confidence, service history, reminders | `manufacturers/boat_models/model_years/oem_equipment`, `vessel_equipment`, `service_records`, `service_reminders` | B:test_equipment*, test_catalogue_*, J:catalogue | RV |
| V02 | HIN capture/decoding/manual fallback; unknown never invented | `services/hin.py`; manufacturer only from recorded MIC; suggestion-only | B:test_hin*, J:catalogue (synthetic MIC decode, explicit accept) | RV |
| V03 | Equipment changes; bounded curation | Owner edits reset verification; admin approve/reject queue; 1,000 CP once per vessel | B:test_equipment*, review regression P5, J:engagement (admin verifies rule) | RV |
| V04 | Source-attributed seed data; synthetic marked | Brand names from the spec table without MIC codes; synthetic manufacturer/products/fitment/knowledge flagged synthetic; no licensed manuals ingested | B:seed tests | RV (real NZ fleet data: DFS via the curation workflow) |
| V05 | Central fitment; unknown never "fits" | `services/fitment.py` used by catalogue, detail, search, AI, checklists | B:test_fitment, test_products_*, J:api_journey, J:engagement (engine change) | RV |
| V06 | Ingestion, embeddings, pgvector, citations; offline substitute | Licence-tracked sources, admission, chunking, HNSW cosine retrieval; `local_hash` + `local_extractive` test-only | B:test_rag_core, test_ai_chat | RV (OpenAI quality: EXT) |
| V07 | Keyword stub / `RAGDocument.title` | Replaced by retrieval service; legacy chunks never retrieved | B:test_rag_core, M:test_migrations | RV |
| V08 | Domain specialists | Shared parameterised registry (12 domains) | B:test_ai_chat | RV |
| V09 | Context binding; untrusted data | Tools bound to user/vessel; delimited tool output; injection filter | B:test_ai_openai_provider (injection), review | RV |
| V10 | Absent/conflicting evidence | `insufficient_evidence` / `conflicting` with clarifying question; per-clause fit-claim guard | B:test_ai_chat, review regressions P3 | RV |
| V11 | Structured product refs; explicit-intent cart action | `products[]` with fitment; `actions[]` executed only via `POST /cart/items` on tap | B:test_ai_chat, J:engagement, J:api_journey | RV |
| VA | Acceptance example (source → cite → verified stocked product → add; change engine / remove source) | As specified | B:test_ai_chat::acceptance, test_integration_journeys, J:engagement | RV |

### 3.5 Checklists, rewards, delivery, notifications (brief §8)

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| K01–K05 | Tiers + inheritance + tailoring; persistence; fitment linking; predictable add-missing; delete/regenerate/export; spares ≠ compliance | `services/checklists.py`, export HTML/CSV with disclaimer | B:test_checklists*, J:catalogue (reload persistence, add-missing 7 then 0, exports) | RV |
| R01–R03 | Award once from authentic paid events; ledger; refund reversals; concurrency-safe; paid spend; NZ periods | Locked ledger with idempotency keys; owed points; bonus clawback | B:test_loyalty_*, review regressions P1/P2, follow-ups | RV |
| R04 | Multiple crews | One crew per user (unique), deterministic captain hand-over | B:test_crew_rules | RV |
| R05 | Discount entitlement single use; experience fulfilment record | `DiscountEntitlement` reserved→consumed; `ExperienceRedemption` lifecycle | B:test_loyalty_redemption, test_integration_journeys | RV |
| R06 | Team management and redemption UI | Crew Rewards tabs | J:engagement (crew + invite accepted in second browser) | RV |
| R07 | No invented experiences | Catalogue unavailable → no items, 503 on redeem | B:test_loyalty_redemption | RV (Strapi live: EXT) |
| H01–H02 | Destination capture, server quotes; delivery from paid event | Map pin limited to enabled areas; delivery created by `events.order_paid` | B:test_helm_dash_flow, J:commerce | RV |
| H03 | Dispatch/operator UI and transitions | Responsive web consoles; transition table; active-operator checks | J:commerce (assign → accept → picked up → delivered) | RV |
| H04 | Authentic tracking; simulation labelled; no interpolation | Latest reported position only; `simulated` labelled | J:commerce (browser geolocation reading shown as device report) | RV |
| H05 | Operating areas / unavailable states | Admin-managed areas; outside area → 422 | B:test_shipping_quotes | RV |
| H06 | Courier rates, label/tracking boundaries | Rate card + adapter boundary; local contract adapter (test shipments) | B:test_commerce_lifecycle (shipment) | EXT (NZ Post/Aramex credentials + docs) |
| H07 | Payout records/reconciliation; live disabled | `OperatorPayout` (`rate_unconfigured` without share), approval, reconciliation | B:test_dispatch_admin | EXT (live payouts disabled; Stripe Connect not implemented) |
| H08 | No certification/DG claims | DG items restricted to configured delivery types; certification stored as unverified text | B:test_shipping_quotes | RV |
| N01–N03 | Outbox, retries, preferences, reminders, CMS; local sinks; handlers | Outbox with backoff/dead-letter; Resend/FCM adapters; Mailpit sink locally | B:test_notifications_*, J:api_journey (order email in Mailpit) | RV locally; EXT (Resend/FCM credentials) |

### 3.6 Build and deployment (brief §9)

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| B01 | Undeclared Gunicorn | Declared (`gunicorn`, `uvicorn-worker`), hashed locks | image build | RV |
| B02 | Docker builder tests needed absent files | Tests run outside the image or in the optional `test` target | image builds (prod, dev, test target) | RV |
| B03 | Real migrations; empty install and representative upgrade | 0001 (exact Phase-7 DDL), 0002 (data-preserving backfills), 0003 | M:test_migrations (legacy data upgrade, no drift, constraint names), J:empty-DB migrate in containers | RV |
| B04 | Flutter platform scaffolding; missing font | web/android/ios/macos/windows generated; unused font removed | flutter build web | RV (store signing/icons: DFS with brand assets) |
| B05 | Locked dependencies | `requirements*.lock` (hashed), `pubspec.lock` | builds | RV |
| B06 | Celery tasks referenced but absent | All scheduled tasks implemented and registered; heartbeat → `/ready` | B:test_tasks_ops, container logs | RV |
| B07 | Typesense collection and sync | Collection provisioning, full + incremental sync, Postgres fallback | B:test_search*, container `sync-search` | RV |
| B08 | Compose interpolation/networking/ports | `${VAR:?}`; internal networks; only proxy + mail UI published | `docker compose config`, `docker port` | RV |
| B09 | HTTPS proxy, health/readiness, least privilege, sequencing, backup/restore, rollback | nginx TLS template, non-root read-only containers, migrate one-shot, backup/restore scripts, runbook | deploy harness (§5) | RV locally; production run: BLK (no authority/host) |
| B10 | Deployment branch commit; fail closed | Adapted; deploy.sh exits non-zero on build/migration/readiness failure | deploy harness | RV |
| B11 | Production bundle API config | dart-defines; build preflight refuses localhost for production | release build checks | RV |
| B12 | Image/error/loading states, a11y, responsive | Placeholders, retry states, semantics tree on web, rail/bottom nav | F:widget tests, browser journeys | RV (formal WCAG audit not performed) |
| B13 | Measured performance vs targets | `scripts/perf/measure_api.py` | §5 | see §5 |

## 4. Contract conventions, decisions and defaults

**API contract (canonical, shared by backend and Flutter):**

- Field names are the database/Pydantic names (`nickname`, `stock_quantity`,
  `weight_grams`, `hull_type`, ...). Request models reject unknown fields (422), so a
  client cannot smuggle `id`, `role` or legacy names such as `name`.
- Money is integer NZD cents in fields ending `_cents`, plus `currency: "NZD"`. The
  server computes every price, subtotal, discount, shipping and total.
- Errors are `{"detail": <message>, "code": <machine code>}`; validation errors add
  `errors`. Provider/internal exception text is never returned.
- Timestamps are ISO-8601 with timezone; identifiers are UUID strings.

**Decisions (conservative, configurable, no unsupported entitlement/charge/payout):**

| # | Decision |
|---|---|
| D1 | Roles `customer`/`operator`/`dispatcher`/`admin` live only in `users.role`; changed by an admin endpoint (audited, last admin protected) or the `grant-role` CLI. Token claims and user metadata are ignored for authorization. |
| D2 | Tokens are verified with Supabase signing keys: `AUTH_MODE=jwks` (ES256/RS256/EdDSA from the project JWKS) or `AUTH_MODE=hs256` with the server-only legacy JWT secret. `exp`/`iat`/`iss`/`aud`/`sub` required; anon/service-role/anonymous tokens refused. There is no unverified development bypass; local development uses a real local GoTrue issuer. |
| D3 | Local profile id = verified `sub`; email from the verified token. Provisioning is idempotent; an email already bound to another subject is refused (409) rather than re-bound. |
| D4 | Money stored and transported as integer cents; legacy NUMERIC values converted half-up by migration 0002. |
| D5 | Local substitutes (local payments, deterministic embeddings/extractive answerer, fixture CMS, SMTP sink) are refused at start-up outside `development`/`test`. |
| D6 | The First Mate uses a bounded OpenAI tool-calling loop implemented directly with the OpenAI SDK. LangChain/LlamaIndex were removed: the Phase-7 code imported `AgentExecutor`, which no longer exists in current LangChain, so that path could not run. |
| D7 | Afterpay and Laybuy are not offered (no validated merchant integration); the client shows the recorded reason and never renders a card-backed substitute. |
| D8 | Courier pricing uses an explicitly configured merchant rate card; NZ Post/Aramex API adapters and live label booking stay disabled until credentials and documentation are validated. Production has no default rate card. |
| D9 | Products flagged `dangerous_goods` may only use the delivery types in `DANGEROUS_GOODS_DELIVERY_TYPES` (default `click_and_collect`). No software flag asserts carrier approval. |
| D10 | Helm Dash operator payout share is unset by default: payout records are created as `rate_unconfigured` with no amount; live payouts are disabled. |
| D11 | Migration 0002 carries legacy fitment rules as `unverified` (they were never verified), so they no longer produce a positive "fits". |
| D12 | Crew spend counts points earned while a member (the crew is recorded on each earn row); spend before joining does not count. Crews need ≥ 2 members for a multiplier. |
| D13 | The "Crew Wallet" is the displayed aggregate of members' balances; only the owner can spend their own points (no shared spending authority is specified). |
| D14 | Refunds reverse earned points proportionally; points already spent become `points_owed`, settled from later credits; a refund in a closed month claws back the excess crew bonus; a fully refunded order returns the points spent on its discount. |
| D15 | Profile-verification bonus (1,000 CP) is paid once per vessel. |
| D16 | Email confirmation is verified server-side through the Supabase Admin API (service-role key, required in production); `user_metadata` is never trusted. |
| D17 | Products flagged dangerous goods and the delivery-type allowlist are configuration; operator certification is stored as unverified text and never shown as a platform certification. |
| D18 | Customer search goes through the API (`/search/products`), not Typesense directly, so fitment stays centralised; Typesense is a prefilter and Postgres is the fallback. |
| D19 | Admin refunds need a per-request `Idempotency-Key`; crew invites are capped at 20 per crew per rolling day. |
| D20 | Points tier (deckhand…captain) is display-only and creates no cashback entitlement. |

## 5. Validation log

Commands, environment, SHA, results.

## 6. Checkpoint (for continuation across sessions)

- 2026-11-05: preflight complete; heads verified (`main@49877e2`,
  `claude/helm-marine-platform-Vrt0W@421deef`, unchanged since review); plan recorded.
- 2026-11-05: Phase A foundation landed on `claude/new-session-bkkwp6` (`36d0251`…`85332b0`):
  config validation, verified auth, roles, schema + migrations 0001/0002 with legacy-data
  upgrade proof, cents, cart service, central fitment, Celery registry, CLI, PostgreSQL
  tests (55 passing). Parallel workstreams started from `1934508`: commerce,
  catalogue/vessel data, knowledge/First Mate, rewards/delivery/notifications, Flutter
  foundation, build/deployment. Next: integrate workstream branches, add a merge
  migration if several add revisions, Flutter pass 2 (checkout, chat, checklists,
  rewards, dispatch), independent review, full validation, land on `main`.
