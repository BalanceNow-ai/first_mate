# Helm / First Mate — Repair Programme: Plan, Closure Table and Checkpoint

This is the **canonical development plan and closure record** for the repair programme
started 2026-11-05 against `main@49877e2`. It supersedes the phase prompts in
`docs/07_code_reviews/` as the statement of what is actually implemented. Earlier
review approvals and the historical "115 passed" figure are **not** evidence for
anything recorded here; every status below cites fresh validation.

**2026-11-06 correction increment.** An independent review of the landed
`main@f4f3a97` reproduced five defects (FM-01…FM-05, §3.7). The affected rows (V05, V09,
V10, C08, R01–R03, N01–N03) were reopened and are re-closed below only with the new
proof; H06 and H07 are split into what exists and what is not implemented.

Status vocabulary (one per row):

- `RESOLVED_AND_VERIFIED` — implemented and proven by executed tests / journeys listed.
- `IMPLEMENTED_EXTERNAL_VALIDATION_PENDING` — code path complete and contract-tested
  locally; needs the named credential / partner to validate live. The production
  feature is disabled (or rejected) until configured.
- `BLOCKED` — a concrete unavailable dependency or authority boundary prevents it.
- `DEFERRED_FUTURE_SCOPE` — explicitly later rollout breadth only.
- `SPECIFIED_NOT_IMPLEMENTED` — owner-requested scope with an accepted written contract; no implementation or verification claimed.

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
| C08 | Refunds and partial refunds | Cumulative refund deltas; restock only for full pre-dispatch refunds; earned-point reversal, crew-bonus recomputation and discount-point return run independently (FM-03); undispatched Helm Dash job cancelled; one global lock order (D22, FM-05) | B:test_commerce_lifecycle, test_loyalty_ledger, test_refund_compensation (signed refund events, replays, racing redemption), test_lock_order (two-connection races), review follow-ups | RV (reopened by FM-03/FM-05, re-closed) |
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
| V05 | Central fitment; unknown never "fits"; no declared restriction ignored | `services/fitment.py` used by catalogue, detail, search, AI, checklists; one rule-scope contract (`core/fitment_rules.py`) in request validation, verification, DB CHECKs (0004) and — fail closed for legacy rows — the evaluator; `cli fitment-audit` | B:test_fitment, test_fitment_scope_contract (schema → DB → verify → detail/list/search/AI), test_products_*, J:api_journey, J:engagement (engine change) | RV (reopened by FM-02, re-closed) |
| V06 | Ingestion, embeddings, pgvector, citations; offline substitute | Licence-tracked sources, admission, chunking, HNSW cosine retrieval; `local_hash` + `local_extractive` test-only | B:test_rag_core, test_ai_chat | RV (OpenAI quality: EXT) |
| V07 | Keyword stub / `RAGDocument.title` | Replaced by retrieval service; legacy chunks never retrieved | B:test_rag_core, M:test_migrations | RV |
| V08 | Domain specialists | Shared parameterised registry (12 domains) | B:test_ai_chat | RV |
| V09 | Context binding; untrusted data; a citation must support its sentence | Tools bound to user/vessel; delimited tool output; injection filter; claim/evidence support contract (D21): a claim survives only when a passage its own sentence cites contains its numbers, units, identifiers and polarity; answers carry the supporting passage per claim | B:test_ai_openai_provider (injection), test_grounding_support (review probes G1–G4, 9 adversarial classes, both providers through the API) | RV (reopened by FM-01, re-closed; the check is lexical — see D21 limits; OpenAI answer quality: EXT) |
| V10 | Absent/conflicting/unsupported evidence | Non-grounded answers are a controlled limitation + clarifying question (the draft is discarded; only catalogue/fitment-checked product statements remain); evidence, applicability, fitment and proposals revalidated at answer time | B:test_ai_chat, test_grounding_support (revoked source / changed engine during the model call), review regressions P3 | RV (reopened by FM-01, re-closed) |
| V11 | Structured product refs; explicit-intent cart action | `products[]` with fitment; `actions[]` executed only via `POST /cart/items` on tap | B:test_ai_chat, J:engagement, J:api_journey | RV |
| VA | Acceptance example (source → cite → verified stocked product → add; change engine / remove source) | As specified | B:test_ai_chat::acceptance, test_integration_journeys, J:engagement | RV |

### 3.5 Checklists, rewards, delivery, notifications (brief §8)

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| K01–K05 | Tiers + inheritance + tailoring; persistence; fitment linking; predictable add-missing; delete/regenerate/export; spares ≠ compliance | `services/checklists.py`, export HTML/CSV with disclaimer | B:test_checklists*, J:catalogue (reload persistence, add-missing 7 then 0, exports) | RV |
| R01–R03 | Award once from authentic paid events; ledger; refund reversals; concurrency-safe; paid spend; NZ periods | Locked ledger with idempotency keys; owed points; bonus clawback on every refund that lowers net spend; discount points returned once on full refund (D14) independent of earned points; multi-account paths lock in one order (D22) | B:test_loyalty_*, test_refund_compensation, test_lock_order, review regressions P1/P2, follow-ups | RV (reopened by FM-03/FM-05, re-closed) |
| R04 | Multiple crews | One crew per user (unique), deterministic captain hand-over | B:test_crew_rules | RV |
| R05 | Discount entitlement single use; experience fulfilment record | `DiscountEntitlement` reserved→consumed; `ExperienceRedemption` lifecycle | B:test_loyalty_redemption, test_integration_journeys | RV |
| R06 | Team management and redemption UI | Crew Rewards tabs | J:engagement (crew + invite accepted in second browser) | RV |
| R07 | No invented experiences | Catalogue unavailable → no items, 503 on redeem | B:test_loyalty_redemption | RV (Strapi live: EXT) |
| H01–H02 | Destination capture, server quotes; delivery from paid event | Map pin limited to enabled areas; delivery created by `events.order_paid` | B:test_helm_dash_flow, J:commerce | RV |
| H03 | Dispatch/operator UI and transitions | Responsive web consoles; transition table; active-operator checks | J:commerce (assign → accept → picked up → delivered) | RV |
| H04 | Authentic tracking; simulation labelled; no interpolation | Latest reported position only; `simulated` labelled | J:commerce (browser geolocation reading shown as device report) | RV |
| H05 | Operating areas / unavailable states | Admin-managed areas; outside area → 422 | B:test_shipping_quotes | RV |
| H06a | Courier rates; manual fulfilment and tracking entry | Configured rate card; staff record carrier + tracking number; local contract adapter (test shipments, local environments only) | B:test_commerce_lifecycle (shipment) | RV (rate card / manual fulfilment) |
| H06b | Live NZ Post / Aramex booking, labels and tracking | **Not implemented.** `courier.get_adapter` refuses outside local environments; start-up rejects live booking | config tests | BLK (needs carrier API documentation and test accounts to build against — not merely credentials) |
| H07a | Payout records, approval, reconciliation | `OperatorPayout` (`rate_unconfigured` without share), approval, reconciliation | B:test_dispatch_admin | RV (records only; no money moves) |
| H07b | Live operator payouts | **Not implemented** (no Stripe Connect provider); start-up rejects live payouts | config tests | BLK (needs a Stripe Connect platform account and a payout design decision) |
| H08 | No certification/DG claims | DG items restricted to configured delivery types; certification stored as unverified text | B:test_shipping_quotes | RV |
| N01–N03 | Outbox, retries, preferences, reminders, CMS; local sinks; handlers | Outbox with backoff/dead-letter; Resend/FCM adapters; per-device push outcomes — retries go only to devices still pending (FM-04); claim lease renewed per row and fenced by a lease token | B:test_notifications_*, test_push_delivery_outcomes (200/500, 200/429, timeout, invalid, permanent, multi-attempt, expired-lease race), J:api_journey (order email in Mailpit) | RV locally (reopened by FM-04, re-closed); EXT (Resend/FCM credentials). Guarantee: email at-least-once with provider idempotency; push at-least-once per device — a provider call still in flight when its lease expires can be repeated (FCM has no idempotency key), a retry never re-sends to a device recorded as delivered |

### 3.6 Build and deployment (brief §9)

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| B01 | Undeclared Gunicorn | Declared (`gunicorn`, `uvicorn-worker`), hashed locks | image build | RV |
| B02 | Docker builder tests needed absent files | Tests run outside the image or in the optional `test` target | image builds (prod, dev, test target) | RV |
| B03 | Real migrations; empty install and representative upgrade | 0001 (exact Phase-7 DDL), 0002 (data-preserving backfills), 0003, 0004 (fitment scope CHECKs, NOT VALID + audit), 0005 (push outcomes, lease token); compatibility of each with the serving release in the runbook §7a | M:test_migrations (legacy data upgrade, no drift, constraint names), J:empty-DB migrate in containers | RV |
| B04 | Flutter platform scaffolding; missing font | web/android/ios/macos/windows generated; unused font removed; Android minSdk 26 (required by sentry_flutter 10); Stripe push-provisioning excluded from lint classpaths (private Google SDK) | web release build; **Android release APK built** (`flutter build apk --release`, minSdk 26 / target 36, INTERNET permission) | RV for web + Android; iOS/macOS/Windows builds: BLK (need macOS/Xcode or Windows hosts; scaffolding committed); store signing keys/icons: DFS with brand assets |
| B05 | Locked dependencies | `requirements*.lock` (hashed), `pubspec.lock` | builds | RV |
| B06 | Celery tasks referenced but absent | All scheduled tasks implemented and registered; heartbeat → `/ready` | B:test_tasks_ops, container logs | RV |
| B07 | Typesense collection and sync | Collection provisioning, full + incremental sync, Postgres fallback | B:test_search*, container `sync-search` | RV |
| B08 | Compose interpolation/networking/ports | `${VAR:?}`; internal networks; only proxy + mail UI published | `docker compose config`, `docker port` | RV |
| B09 | HTTPS proxy, health/readiness, least privilege, sequencing, backup/restore, rollback | nginx TLS template, non-root read-only containers, migrate one-shot, backup/restore scripts, runbook | deploy harness (§5) | RV locally; production run: BLK (no authority/host) |
| B10 | Deployment branch commit; fail closed | Adapted; deploy.sh exits non-zero on build/migration/readiness failure | deploy harness | RV |
| B11 | Production bundle API config | dart-defines; build preflight refuses localhost for production | release build checks | RV |
| B12 | Image/error/loading states, a11y, responsive | Placeholders, retry states, semantics tree on web, rail/bottom nav | F:widget tests, browser journeys | RV (formal WCAG audit not performed) |
| B13 | Measured performance vs targets (p95 < 200 ms API, < 100 ms search) | `scripts/perf/measure_api.py`; search reuses a keep-alive Typesense client, facets in one query | §5: all targets met at concurrency 1 and 10 on the local stack | RV (local evidence; production performance not measured) |

### 3.7 Independent review of `main@f4f3a97` (2026-11-06)

| ID | Finding (reproduced by the reviewer's probes) | Fix | Proof (each fails on `f4f3a97`, passes now) | Status |
|---|---|---|---|---|
| FM-01 | Answer guard certified contradicted/unsupported sentences as `grounded` because a valid citation index existed; unsupported instructions survived an insufficient-evidence reply | D21 claim/evidence contract; controlled non-grounded reply; claim evidence in the response; answer-time revalidation of sources, applicability, fitment, proposals; system prompt requires per-sentence citations | B:test_grounding_support (31 cases incl. G1–G4, both providers via the API), test_ai_* | RV |
| FM-02 | Rule `{engine F150, vessel_model 2250, year_to 2000}` accepted and evaluated `verified_fit` for a 2022 Rayglass 2500 | Rule-scope contract in schema, verification, DB and evaluator (fail closed); 0004 moves violating rows to `fitment_rule_quarantine` (with reasons) and adds validated constraints identical to the Python contract (blanks absent, years 1900–2100, ordered); audit CLI lists quarantined rules | B:test_fitment_scope_contract (20 cases), M:test_0004_quarantines_malformed_fitment_rules | RV |
| FM-03 | Full refund skipped returning discount points when no earned point remained to reverse (zero-earn order; earlier partial refund) | Independent, idempotent compensation steps; also found and fixed: crew-bonus clawback skipped for a refund crossing a tier without a further whole point | B:test_refund_compensation (6 cases via signed `charge.refunded`) | RV |
| FM-04 | Partial FCM success marked the notification sent and lost the transiently failing device | Per-device outcomes persisted; retry only pending devices; lease renewal + fencing token | B:test_push_delivery_outcomes (7 cases) | RV |
| FM-05 | Opposing lock orders: payment success vs voiding its discount; refund vs operator action | D22 single lock order; also found and fixed: two refunds in one crew locking members' accounts in opposite orders | B:test_lock_order (3 two-connection barrier races; all three raise `DeadlockDetectedError` on `f4f3a97`) | RV |

**Second independent review (of the fixes, `f4f3a97..a95be4a`).** Confirmed: one-word
reversals ("with" for "without", "disable" for "check", "after" for "before") and
cross-sentence recombination still certified; a generic fit claim riding on a verified
product; the lease fence reading the reclaiming worker's token after the first lost
lease; legacy malformed rules not rejectable (500) and blank-string disagreement between
the audit and the constraint. Traced: bonus-run vs refund lock order, deactivated
products and deleted vessels not revalidated, reached devices lost on a lost lease.
All fixed in `42f5b75`;
each confirmed case is a regression test (B:test_grounding_support,
test_push_delivery_outcomes::test_lost_lease_fences_every_later_row_of_the_batch — fails
on the previous code — M:test_0004_quarantines_malformed_fitment_rules).

Additional concerns raised by the first review:

| Concern | Disposition |
|---|---|
| Knowledge applicability covers only vessel/engine make and model | Unchanged and stated (D21 limits). Model-year, serial-range, regional/legal-date or equipment-specific applicability is **not** checked; add those fields before admitting content that depends on them. DFS. |
| No answer-time revalidation of fitment or revoked sources | Implemented (`agent.revalidate`). RV — B:test_grounding_support. |
| Outbox lease outlived by slow batches; no fencing | Implemented (FM-04). RV. |
| Request-start authorization is not continuous | Documented as the model (D23). |
| Migrations run while the previous release serves | Per-revision compatibility and the maintenance requirement for 0002 documented (runbook §7a); 0003–0005 are additive. Production execution BLK (no authority). |
| Android build ≠ distribution | Unchanged: debug-signed APK, no release keystore (B04). |
| Enabled integrations need failure-mode validation, not just keys | Recorded in §6: each external feature stays disabled until its live failure modes are exercised in staging. |

Review probe re-run on the corrected code: `docs/08_delivery/evidence/review_f4f3a97_probes_after.json`
(G1–G3 not certified, G4 instruction suppressed, F1 rejected by the schema and `unknown`
as a legacy row, R1/R2 one restoration each, N1 failing device reported for retry,
identity probes unchanged).

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
| D21 | **Grounding is a per-claim evidence contract** (`services/ai/support.py`). Each clause of a draft is framing, a catalogue/fitment statement about a tool-returned product *named in that clause*, or part of a claim. A claim sentence survives only when ONE sentence (or structured fact) of a passage cited *by that sentence* contains all of its content words (no paraphrase allowance; relation words such as with/without, before/after, on/off and quantifiers count), all its numbers, number+unit pairs and identifiers (normalised: 100-hour = 100 h = 100 hours; 10W-30 = 10W30), and agrees clause by clause in polarity with the passage clause it overlaps most. Unsupported sentences are removed (counted in `removed_statements`), never certified; `grounded` needs ≥ 1 supported claim; otherwise the reply is a controlled limitation + question. Each claim is returned with its supporting passage and the passage's applicability. **Limits:** the check is lexical — inside ONE passage sentence that lists several values it cannot tell which noun each belongs to; it cannot judge whether a passage is true or applies more finely than make/model; faithful paraphrases are removed (fail closed); it does not replace live evaluation of model quality on licensed content. |
| D22 | **Lock order**: `Order → DiscountEntitlement → HelmDashDelivery → crew-period advisory lock (crew, period) → CrewPoints`; several crew-period locks or accounts are taken together, up front, in ascending order (`loyalty.lock_crew_periods`, `loyalty.lock_accounts`). Locking delivery lookups lock the order first; voiding locks the entitlement before the account; a refund cancels the delivery before touching points and takes the crew-period lock before reading bonus recipients; the monthly bonus run takes all its crew-period locks, then all accounts, then re-reads spend. |
| D23 | **Authorization model**: identity, role and ownership are checked at the start of each request, and the request's effects commit in that request's transaction. A role or ownership change takes effect for subsequent requests; there is no continuous re-authorization during a request already in progress. |

## 5. Validation log

Environment: Linux VM, 4 vCPU / 15 GB, Python 3.11 (venv), PostgreSQL 16.15 +
pgvector 0.6.0, Docker 29.9, Flutter 3.47.9 / Dart 3.13, Chromium + Playwright (node).
Source: branch `claude/new-session-bkkwp6`; final numbers below were taken on the
integrated code (head at the time of each run is recorded in the commit history).
External providers were **never** called live: Stripe, OpenAI, Resend, FCM, Strapi and
carriers were exercised only through fakes at the SDK/HTTP boundary or local substitutes.

| Check | Command | Result |
|---|---|---|
| Backend regression (fresh DB) | `cd backend && TEST_DATABASE_URL=…/helm_test_final pytest -q` | **336 passed, 1 skipped** (SMTP-sink integration test: needs Mailpit's SMTP port on the host; container email delivery is proven by the API journey) |
| Migrations | part of the suite: `test_migrations.py` | Phase-7 schema with representative data → 0001 → 0002 → 0003: every backfill asserted; no model/schema drift; CHECK names match models |
| Backend lint/format | `ruff check app alembic && ruff format --check app alembic` | clean |
| Flutter static analysis | `flutter analyze` | No issues |
| Flutter tests | `flutter test` | **303 passed** (incl. contract tests on real server payloads) |
| Android release APK | `flutter build apk --release` (production defines; local Gradle init script mirrors Maven Central because repo.maven.apache.org rate-limited this sandbox) | built `app-release.apk` (82.5 MB), minSdk 26, targetSdk 36, INTERNET permission; signed with the debug key (no release keystore provided) |
| Web release build (production defines) | `flutter build web --release --dart-define=API_BASE_URL=https://… APP_ENV=production` | built; `main.dart.js` contains 0 × `localhost:8000` and the configured https API |
| Web image preflight | `docker build --target preflight …` | refuses http URLs, loopback and missing anon key for production; accepts valid https config |
| Clean stack install | `scripts/local_stack.sh reset --yes && scripts/local_stack.sh up && … seed && … cli sync-search` | exit 0; empty DB migrated to 0003; seed-demo; 32 products indexed; `/ready` → database 0003, redis ok, celery heartbeat fresh |
| API journey (real GoTrue + Mailpit + proxy) | `python scripts/e2e/api_journey.py` | **39/39** |
| Browser: catalogue / vessel / checklists | `node frontend/e2e/catalogue_journey.mjs --app http://localhost:18080` | **12/12** |
| Browser: checkout / Helm Dash / dispatch | `HELM_WEB=http://localhost:18080 node frontend/e2e/commerce_journey.mjs` | **15/15** (decline→retry→paid; dispatcher assign; operator browser-geolocation reading shown as device report) |
| Browser: First Mate / rewards / admin | `WEB_URL=http://localhost:18080 node frontend/e2e/engagement_journey.mjs` | **25/25** (3 consecutive runs) |
| Stripe web Payment Element smoke | `node frontend/e2e/stripe_web_smoke.mjs` (stubbed API, real js.stripe.com, fake key) | Stripe.js injected only at payment; production CSP allows it; fake key → explicit unavailable state, never "paid"; blocked Stripe.js → unavailable state |
| Images / compose / deploy harness | see `Operations_Runbook.md` (build & deployment workstream) | prod/dev/test images build; non-root, read-only, no published data ports; GoTrue both signup modes; `deploy.sh` exits non-zero on failed migration, readiness timeout and build failure without printing success; restore requires explicit confirmation |
| Deploy preflight re-check | `HELM_ENV_FILE=… bash deploy/deploy.sh` (missing / empty values) | exit 1, "Deploy NOT complete", 0 × "Deploy complete" |
| Independent backend review | separate reviewer, probes under `/tmp` | 14 findings (6 proven by failing probes) → all fixed; probes kept as `test_review_regressions.py` |
| Independent client/contract review | separate reviewer | 12 findings → all fixed (H1/H2/M1 in checkout, others in rewards, session storage, build checks, a11y) |

**Correction increment (2026-11-06, code at `42f5b75`, docs at `67bc13e`+).** Same environment.

| Check | Command | Result |
|---|---|---|
| Backend regression (fresh DB, standalone Typesense up) | `TEST_DATABASE_URL=…/helm_test_fm2 pytest -q -rs` | **423 passed, 1 skipped** (SMTP-sink test, as before) |
| Backend lint/format | `ruff check app alembic && ruff format --check app alembic` | clean |
| New regression modules | test_grounding_support, test_fitment_scope_contract, test_refund_compensation, test_push_delivery_outcomes, test_lock_order, test_migrations::test_0004_… | pass; each FM case fails on `f4f3a97` (lock races: `DeadlockDetectedError`) |
| Reviewer probes re-run | `docs/08_delivery/evidence/review_f4f3a97_probes_after.json` | G1–G4 not certified / suppressed; F1 rejected + `unknown`; R1/R2 one restoration; N1 failing device reported; identity unchanged |
| Clean stack install | `local_stack.sh reset --yes && up && seed && cli sync-search && cli fitment-audit` | exit 0; empty DB → 0005; 32 products indexed; 0 malformed fitment rules; `/ready` true, Celery heartbeat fresh |
| API journey | `python scripts/e2e/api_journey.py` | **39/39** |
| Browser journeys | catalogue / commerce / engagement | **12/12**, **15/15**, **25/25** ×3 consecutive |
| Flutter | not re-run | no client source changed in this increment (the new grounding fields are additive and ignored by the client model) |
| Second independent review | separate reviewer on `f4f3a97..a95be4a` | 4 confirmed + 1 low + 3 traced findings → all fixed in `42f5b75` (§3.7) |

Performance (local stack above, 2 API workers, through nginx; 300 requests per
endpoint; **local evidence only — not production performance**):

Concurrency 1:
```
requests=300 concurrency=1 base=http://localhost:18080
endpoint                                          p50     p95     p99  target  err  result
GET /products (public, page 24)                   9.9    13.1    18.2     200    0  PASS
GET /products (vessel, compatible_only)          16.4    19.3    21.2     200    0  PASS
GET /products/{id}                                6.5     7.7     9.5     200    0  PASS
GET /search/products?q=filter                    14.4    18.1    20.6     100    0  PASS
GET /search/products?q=filter (vessel)           18.9    24.1    25.6     100    0  PASS
GET /cart                                         6.8     9.1    10.1     200    0  PASS
GET /vessels                                      7.3     9.4    11.8     200    0  PASS
GET /orders                                       8.8    11.0    12.8     200    0  PASS
GET /loyalty/points                              13.0    16.8    20.8     200    0  PASS
```
Concurrency 10:
```
requests=300 concurrency=10 base=http://localhost:18080
endpoint                                          p50     p95     p99  target  err  result
GET /products (public, page 24)                  30.6    50.8    95.4     200    0  PASS
GET /products (vessel, compatible_only)          60.6    93.1   181.1     200    0  PASS
GET /products/{id}                               17.8    33.5    44.1     200    0  PASS
GET /search/products?q=filter                    42.8    70.1    77.8     100    0  PASS
GET /search/products?q=filter (vessel)           50.1    92.3   108.8     100    0  PASS
GET /cart                                        20.5    39.9    44.8     200    0  PASS
GET /vessels                                     23.4    33.9    38.4     200    0  PASS
GET /orders                                      29.8    44.3    49.9     200    0  PASS
GET /loyalty/points                              60.3    97.0   111.4     200    0  PASS
```

Search is rate-limited per client address (120/min); the measurement raised
`RATE_LIMIT_SEARCH_PER_MINUTE` for the run only. Accessibility: semantics tree enabled
on web, labelled controls and 48 dp targets were checked by widget tests and the
role/label-driven browser journeys; **no formal WCAG 2.1 AA audit was performed**.

## 6. External setup still required (production features stay disabled until then)

| Dependency | Configuration | Feature disabled / refused until provided |
|---|---|---|
| Supabase production project | `SUPABASE_URL`, `AUTH_MODE=jwks` (or legacy `SUPABASE_JWT_SECRET`), `SUPABASE_SERVICE_ROLE_KEY` (server only), client `SUPABASE_ANON_KEY`; enable "Confirm email" | API refuses to start without verifiable auth config / service key |
| Stripe | `PAYMENT_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`; webhook endpoint `/api/v1/payments/webhook` for `payment_intent.*`, `charge.refunded` | checkout shows payments unavailable; start-up refuses stripe without secrets |
| OpenAI | `AI_ENABLED=true`, `LLM_PROVIDER=openai`, `EMBEDDING_PROVIDER=openai`, `OPENAI_API_KEY`; re-embed admitted sources | First Mate returns 503 `ai_unavailable` |
| Licensed knowledge content | ingest via `python -m app.cli ingest-knowledge PATH …`, verify licence, admit | answers report insufficient evidence |
| Resend / FCM | `EMAIL_PROVIDER=resend` + `RESEND_API_KEY`; `PUSH_PROVIDER=fcm` + Firebase service account | start-up refuses sinks; use `disabled` explicitly to run without |
| Strapi CMS | `CMS_PROVIDER=strapi`, `STRAPI_URL`, `STRAPI_API_TOKEN` | experiences/articles show unavailable; no invented items |
| Courier | `COURIER_RATE_MODE=rate_card` + `COURIER_RATE_CARD`; NZ Post/Aramex APIs not implemented | courier delivery hidden; live labels 503 |
| Helm Dash operations | enable operating areas, vet and activate operators, set `HELM_DASH_OPERATOR_SHARE_BPS` | Helm Dash hidden without enabled areas; payouts recorded as `rate_unconfigured`; live payouts not implemented |
| Typesense, Redis, Sentry, PostHog, Mapbox tiles | per runbook | search falls back to PostgreSQL; monitoring off; maps show areas without base tiles |
| Hosting / TLS / DNS | host, certificates, DNS, backups location | **BLOCKED**: no authority to provision or deploy (brief §1) |

A credential alone does not enable a feature: each integration above also needs its
failure modes (timeouts, declines, retries, revoked keys, partial failures) exercised in
a staging environment before it is turned on for customers.

## 7. Checkpoint (for continuation across sessions)

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
- 2026-11-05: all workstreams integrated (backend: commerce, catalogue/vessel data,
  knowledge/First Mate, rewards/delivery/notifications, build/deploy; client: foundation,
  catalogue/vessels/checklists, checkout/orders/Helm Dash/dispatch, First Mate/rewards/
  admin, Stripe web Payment Element). Two independent reviews (backend 14 findings,
  client 12 findings) fixed. Final validation recorded in §5; Android release APK built;
  PR BalanceNow-ai/first_mate#8 opened for merge into `main`.
- 2026-11-06: independent review of `main@f4f3a97` (5 findings) → correction increment
  on `claude/new-session-bkkwp6`: FM-01 `e1e086b`, FM-02 `5868cf7`, FM-03 `a5547c3`,
  FM-04 `a14b378`, FM-05 `b1a8bac`; migrations 0004/0005; affected rows re-closed (§3.7);
  validation in §5 (correction increment rows).
- **Next (outside this programme's authority):** provide the §6 credentials in a
  staging environment and run live validation of Stripe (incl. 3-D Secure and webhooks),
  Supabase JWKS, OpenAI quality on licensed content, Resend/FCM, Strapi; provision
  hosting/TLS/DNS; sign mobile builds; formal WCAG audit; production load test.


## 8. Service-jobs extension — specified 6 November 2026

The owner requested guided problem photos and access information, likely parts and measurements, reciprocal feedback, and “understand my invoice.” This is a new bounded MVP alongside the repair record above. Existing closure evidence is preserved; this documentation update neither verifies new code nor reopens previously corrected defects.

- Canonical detailed contract: [Service Jobs and Contractor Assistant](../04_technical_spec/Service_Jobs_and_Contractor_Assistant_Specification.md), version 1.0.
- Master specification: Features 4–7; product design includes this extension.
- Delegated delivery instructions: [Claude Code build prompt](Service_Jobs_Claude_Code_Build_Prompt.md).
- Source baseline inspected for this specification: `main@1ba32445a7f84a0b356682d8f5bb28ffb3711e5f`.
- Work order: shared job/grants/private media → guided capture/measurements/brief/scope → invoice explanation → reciprocal feedback/moderation → integrated verification and landing. Complete all four capabilities; use provider substitutes/manual paths to avoid deferring a whole feature for missing live credentials.

| Requirements | Scope | Status | Evidence / next action |
|---|---|---|---|
| SJ-01–SJ-03 | Persisted adaptive capture, unclear evidence, safe gaps | SPECIFIED_NOT_IMPLEMENTED | Implement owner capture/resume and missing-evidence flows |
| SJ-04–SJ-05 | Dimensions, provenance, provisional parts and unknown suitability | SPECIFIED_NOT_IMPLEMENTED | Implement typed measurements and catalogue/fitment reuse |
| SJ-06–SJ-07 | Contractor organization grants, isolation, revocation and stale publication | SPECIFIED_NOT_IMPLEMENTED | Implement membership, section grants and worker checks |
| SJ-08–SJ-10 | Revisioned brief, requests, confirmation invalidation and explicit scope changes | SPECIFIED_NOT_IMPLEMENTED | Implement owner/contractor preparation and exact-revision decisions |
| SJ-11–SJ-15 | Source-linked invoice explanation, arithmetic, questions and standalone uploads | SPECIFIED_NOT_IMPLEMENTED | Implement extraction/correction/comparison with manual/provider paths |
| SJ-16–SJ-18 | Reciprocal eligibility, blind reveal, responses and moderation | SPECIFIED_NOT_IMPLEMENTED | Implement private job-specific feedback and 14-day lifecycle |
| SJ-19–SJ-22 | Media security, injection resistance, concurrency and outages | SPECIFIED_NOT_IMPLEMENTED | Execute concrete negative and recovery cases |
| SJ-23–SJ-24 | Real Flutter/API/local storage journeys and affected regressions | SPECIFIED_NOT_IMPLEMENTED | Execute integrated acceptance; record exact code identities and limitations |

The implementer must split these grouped rows into individual requirement dispositions where outcomes differ, cite executed checks, and distinguish code not implemented from code implemented with live validation pending. No new hosted CI is required by this extension.

### Implementation record (started 2026-11-06 from `main@2566107`)

Preflight: repository `BalanceNow-ai/first_mate`, branch `claude/new-session-bkkwp6`
restarted from `main@2566107` (the specification commit after `1ba3244`). The correction
increment (FM-01…FM-05, D21–D23) is preserved. Gaps found: no object storage, media
decoding, PDF handling, contractor identity, job/grant model, invoice or feedback model
existed; the reusable parts are auth/roles, the audit log, notification outbox, Celery
with leases, central fitment/catalogue, the AI provider pattern and the Flutter shell.
Dependency order: data model + authorization + run fencing → private media → jobs/grants/
requests → measurements/preparation/brief/scope ∥ invoices ∥ feedback/moderation →
Flutter journeys → integrated acceptance.

| ID | Decision |
|---|---|
| SJ-D1 | One migration (0006) creates every service-jobs table up front (`app/models/service_jobs.py`); composite foreign keys keep child rows on their parent's job (asset↔request, observation/measurement↔asset, visit↔assignment, invoice↔owner's own job). |
| SJ-D2 | Contractor organizations and memberships are separate from Helm Dash roles. Memberships are provisioned by an audited admin/CLI action; org admins manage which members work an assignment; a platform admin has no implicit job-content access; the new `moderator` role is case-scoped. |
| SJ-D3 | Authorization is evaluated per request (`services/service_jobs/access.py`, D23): owner, or an *assigned* member of the organization holding the job's one live **accepted** assignment, limited to owner-granted sections; `access_restricted` additionally needs a per-member flag. Anyone else gets 404; an assigned member asking for an unshared section gets 403. |
| SJ-D4 | Background work is bound to the job `evidence_revision`, asset versions, invoice revision and assignment, claimed with a lease + fencing token and published only after re-checking authority and versions (`services/service_jobs/runs.py`); stale output is kept only as a `superseded` diagnostic. No DB lock is held during provider/scanner/storage calls. |
| SJ-D5 | Local acceptance object store: VersityGW (S3 API over a private volume) — MinIO images are not obtainable from this environment. Production uses any private S3-compatible bucket (`OBJECT_STORE_BACKEND=s3`); `local_fs` is test-only and refused outside development/test. |
| SJ-D6 | Scanning: `clamd` in production; `local_signature` (EICAR + structural checks — **not** a malware scanner) only in development/test; any scanner failure keeps the upload quarantined. |
| SJ-D7 | Vision/OCR/extraction providers: `local_fixture` (development/test substitute: proves orchestration and contracts, not visual accuracy), `openai` (configured path; live evaluation pending separate spend authority) and `disabled` (manual capture/measurement/correction paths stay fully usable). |
| SJ-D8 | Money: invoice amounts are exact decimals in the invoice's stated currency (Numeric(14,4) + ISO code, nulls kept); estimates are integer minor units with a currency. No arithmetic is delegated to a model. |

### Extension decisions and limits

1. Feedback is reciprocal, private and job-specific by default; blind until both submit or 14 days. Public contractor reviews are future opt-in scope; public owner scores/blacklists and automated penalties are excluded.
2. Photographs establish observations, not exact unscaled measurements or verified application suitability. Distinguish owner measurement, contractor confirmation and source verification.
3. Sharing grants, scope acceptance, purchases, payments and feedback publication are deterministic authorized actions; model/OCR text cannot confer authority.
4. Invoice explanations preserve document evidence and calculate amounts deterministically; missing approval records produce questions, not accusations.
5. Build authority covers local implementation/verification and repository landing. Production deployment/migration, paid calls/provisioning, live messages, payments and public reputation effects remain outside automatic authority. Complete local/manual/provider-adapter work without waiting for production credentials.
6. Preserve existing architecture and repair decisions (including D21–D23); contractor membership is separate from delivery/operator roles.
