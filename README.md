# First Mate — Helm Platform

**New Zealand's smartest marine parts and fishing equipment platform.**

This repository contains all product design, research, technical specifications, and development assets for the **Helm** platform — a next-generation B2C marine e-commerce ecosystem built for the New Zealand market.

---

## Repository Structure

```
first_mate/
├── backend/                  # FastAPI API, Celery workers, Alembic migrations, tests (PostgreSQL)
├── frontend/                 # Flutter client (web, Android, iOS, macOS, Windows) + e2e journeys
├── deploy/                   # nginx, deploy/backup/restore scripts (fail closed)
├── scripts/                  # local_stack.sh, build.sh, e2e/ and perf/ tooling, fixture capture
├── docker-compose.yml        # local acceptance stack (GoTrue, Mailpit, Postgres+pgvector, Redis, Typesense,
│                             #   private S3-compatible object store for service-job media)
├── docker-compose.prod.yml   # production topology (external Supabase)
└── docs/
    ├── 01_research/ … 07_code_reviews/   # research, specs, wireframes, historical phase reviews
    └── 08_delivery/          # canonical plan + closure table, runbook, OpenAPI contract
```

## Status

The canonical, evidence-backed status of every requirement is the closure table in
[`docs/08_delivery/Repair_Programme.md`](docs/08_delivery/Repair_Programme.md). It also
lists the external credentials still required (Stripe, Supabase production project,
OpenAI, Resend/FCM, Strapi, carrier APIs). Nothing here is claimed to be live in
production.

## Running it locally

```bash
cp .env.example .env
scripts/local_stack.sh up      # builds images + web bundle, migrates, starts everything
scripts/local_stack.sh seed    # synthetic demo data (local only)
```

Then open http://localhost:18080 (confirmation emails arrive in Mailpit at
http://localhost:18025). Backend tests: `cd backend && pytest -q` against a disposable
PostgreSQL database (`TEST_DATABASE_URL`). Client: `cd frontend && flutter test`.
Operations, production prerequisites and rollback: `docs/08_delivery/Operations_Runbook.md`.

## Key Documents

| Document | Description |
|---|---|
| `docs/08_delivery/Repair_Programme.md` | **Current plan, decisions and closure table** — start here |
| `docs/04_technical_spec/Helm_Platform_Full_Specification.md` | Master product specification |
| [Service Jobs specification](docs/04_technical_spec/Service_Jobs_and_Contractor_Assistant_Specification.md) | Guided photos, measurements, contractor preparation, invoice understanding and private reciprocal feedback (new specified scope) |
| [Claude Code service-jobs build prompt](docs/08_delivery/Service_Jobs_Claude_Code_Build_Prompt.md) | Delegated implementation, verification and landing instructions |
| `docs/05_wireframes/index.html` | **Interactive UI mockups** — open in browser |
| `docs/03_product_design/NZ_Marine_Platform_Product_Design.md` | Full platform product design |
| `docs/03_product_design/RAG_and_Checklist_Design_Specification.md` | AI agent & RAG architecture |
| `docs/03_product_design/Helm_Boat_Database_Design_Specification.md` | Boat OEM database design |
| `docs/03_product_design/Helm_Platform_Feature_Specification_Loyalty_and_Delivery.md` | Crew Rewards & Helm Dash |
| `docs/02_competitive_analysis/NZ_Competitor_Category_Analysis.md` | Burnsco vs Marine Deals analysis |
| `docs/01_research/SKU_Intelligence_and_Data_Sources_Report.md` | High-volume SKU intelligence |

## Platform Vision

Helm is built on three pillars that no NZ competitor currently offers:

1. **My Vessel Garage** — Every customer registers their boat(s) by HIN. The entire platform filters to show only compatible parts, and a service reminder engine tracks maintenance schedules.

2. **First Mate AI** — A personal AI assistant backed by a suite of domain-expert RAG agents (Engine Pro, Electrical Sage, Game Fishing Expert, etc.). Knows the customer's boat, purchase history, and projects.

3. **Helm Dash** — On-demand maritime delivery direct to a vessel at anchor, operating in the Hauraki Gulf, Bay of Islands, Marlborough Sounds, and Tasman Bay via a network of certified water taxi partners.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Flutter (iOS, Android, Web, Windows, macOS) |
| Backend | Python 3.11 + FastAPI |
| Database | PostgreSQL 16 + pgvector |
| AI Orchestration | Bounded OpenAI tool-calling loop + pgvector RAG (decision D6) |
| LLM | OpenAI (`OPENAI_CHAT_MODEL`, default gpt-4.1-mini); deterministic local substitute for tests |
