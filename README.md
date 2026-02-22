# First Mate — Helm Platform

**New Zealand's smartest marine parts and fishing equipment platform.**

This repository contains all product design, research, technical specifications, and development assets for the **Helm** platform — a next-generation B2C marine e-commerce ecosystem built for the New Zealand market.

---

## Repository Structure

```
first_mate/
├── docs/
│   ├── 01_research/              # Market research, SKU intelligence, NZ data
│   ├── 02_competitive_analysis/  # Burnsco, Marine Deals, Smart Marine audits
│   ├── 03_product_design/        # Full product design specs (AI agents, loyalty, delivery, boat DB)
│   ├── 04_technical_spec/        # Full technical specification, architecture, FDD/TDD features
│   └── 05_wireframes/            # Interactive HTML wireframes (open index.html in browser)
└── README.md
```

## Key Documents

| Document | Description |
|---|---|
| `docs/04_technical_spec/Helm_Platform_Full_Specification.md` | **Master specification** — start here |
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
| AI Orchestration | LangChain / LlamaIndex |
| LLM | OpenAI GPT-4.1 / Anthropic Claude 3 |
