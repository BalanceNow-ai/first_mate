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

Filled in as work lands; see §5 for the validation log.

| ID | Finding / requirement | Implementation | Proof | Status |
|---|---|---|---|---|
| _pending_ | | | | |

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

## 5. Validation log

Commands, environment, SHA, results.

## 6. Checkpoint (for continuation across sessions)

- 2026-11-05: preflight complete; heads verified (`main@49877e2`,
  `claude/helm-marine-platform-Vrt0W@421deef`, unchanged since review); plan recorded.
