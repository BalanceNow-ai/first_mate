# Helm Platform: Production Boat OEM Database
## Design Specification & Data Acquisition Strategy

**Prepared by Manus AI | February 2026**

---

## 1. The Problem: No Marine Equivalent of the Automotive ACES Standard

The automotive aftermarket is built on a mature, industry-wide data standard. **ACES** (Aftermarket Catalog Exchange Standard) governs how parts fitment data — year, make, model, engine, transmission — is structured and exchanged across the entire supply chain. **PIES** (Product Information Exchange Standard) governs how product data is structured. Together, they enable any auto parts retailer to answer the question "does this part fit my car?" with near-perfect accuracy. This standard has been developed over decades by the Auto Care Association and is now the backbone of every major automotive e-commerce platform.

**No equivalent standard exists for the marine industry.** The marine sector is significantly more fragmented, with thousands of small manufacturers globally, far fewer industry-wide data initiatives, and a much lower level of e-commerce maturity. The closest commercial offerings are:

| Database | Coverage | What It Provides | What It Lacks |
|---|---|---|---|
| **ABOS Marine Blue Book** (Price Digests) | 1976–present, global | Values, specs (Year/Make/Model/Submodel), engine data | Granular OEM equipment lists (e.g., what chartplotter was fitted standard) |
| **MarineLink™** (Power Systems Research) | Europe & North America | Boat builder production data, engine supplier installations | NZ/Pacific brands; consumer-facing fitment data |
| **TheBoatDB** | Global (600+ makers) | Performance specs, hull dimensions, comparison tools | OEM equipment fitment; NZ-specific models |
| **SearchBoatsOnline** | Primarily US | Manufacturer specs, standard features | NZ brands; historical model year data |
| **NZ Boat Register** | NZ vessels | Ownership, HIN, basic registration data | Make/model specs; OEM equipment |

The conclusion is clear: **the database we need does not exist and must be built.** This is not a weakness — it is a significant commercial opportunity. The first platform to build a comprehensive, NZ-focused production boat OEM database will own a proprietary data asset that competitors cannot easily replicate.

---

## 2. What the Database Must Contain

The database needs to answer three questions for any registered production boat in New Zealand:

1. **What was it born with?** — The factory-standard equipment fitted to that specific model year.
2. **What could it have been fitted with?** — The factory-optional extras available for that model year.
3. **What does it need?** — The compatible service parts, consumables, and upgrades for the specific equipment installed.

This three-layer model transforms the database from a static reference into a dynamic, revenue-generating engine for the platform.

---

## 3. The NZ Market: Target Models for Phase 1

New Zealand has one of the highest rates of boat ownership per capita in the world. The market is dominated by aluminium trailer boats from Australian and NZ manufacturers, with a smaller but high-value segment of fibreglass sports and game fishing boats. The Phase 1 database should cover the following priority brands and model families, which collectively represent the majority of the NZ fleet:

| Priority | Brand | Key Models | Country |
|---|---|---|---|
| **Tier 1** | Stabicraft | 1550 Frontier, 1850 Frontier, 2050 Supercab, 2250 Ultracab | NZ |
| **Tier 1** | Haines Hunter | SF545, SF585, R6, V17, V19, 650R | Australia |
| **Tier 1** | Quintrex | 430 Fishabout, 481 Fishabout, 530 Renegade | Australia |
| **Tier 1** | Rayglass | Legend 2200, 2500, 2700, 3000, 3500 | NZ |
| **Tier 2** | Stessco | 490 Catcher, 540 Catcher, 600 Catcher | Australia |
| **Tier 2** | Extreme Boats | 529 Game King, 599 Game King, 699 Game King | NZ |
| **Tier 2** | Buccaneer | 540 Offshore, 580 Offshore | NZ |
| **Tier 2** | Protector | 650 Offshore, 720 Offshore | NZ |
| **Tier 3** | Riviera | 4400 Sport Yacht, 5400 Sport Yacht | Australia |
| **Tier 3** | Maritimo | M50, M55, M60 | Australia |

---

## 4. The Three-Pronged Data Acquisition Strategy

Because no single source of truth exists, the strategy must combine three concurrent streams of data acquisition. Each stream feeds and validates the others.

### 4.1. Stream 1: Internal Curation (The Foundation)

A dedicated internal data team will manually research and enter the OEM equipment specifications for all Tier 1 and Tier 2 models, covering the last 10 model years. This is a structured, repeatable process using a defined set of primary sources.

**Primary Sources for Manual Curation:**

| Source Type | Examples | Data Available |
|---|---|---|
| **Manufacturer brochures** | Stabicraft.com, Haineshunter.co.nz | Standard & optional equipment lists, specifications |
| **Dealer specification sheets** | Bays Boating, Haines Hunter Taupo | Model-year-specific standard equipment |
| **Marine magazine reviews** | NZ Fishing World, Boating NZ, Power Boat Magazine | Detailed walkthroughs of standard fitment |
| **YouTube video reviews** | Boat reviews from NZ dealers and media | Visual confirmation of fitted equipment |
| **Owner's manuals** | Available from manufacturer websites or user uploads | Definitive list of installed components |
| **Archived brochures** | Wayback Machine, manufacturer archives | Historical model year data |

**Estimated Effort:** Approximately 4–6 hours of research per model year per model. For 30 models × 10 years = 300 model-year records, this represents approximately 1,200–1,800 hours of initial data entry work, which can be completed by a small team in 3–6 months.

### 4.2. Stream 2: User Crowdsourcing (The Scale Engine)

To scale the database beyond the initial curated set and keep it current, the platform will leverage its user base through a structured, incentivised crowdsourcing programme.

**The User Flow:**

When a user adds a vessel to their "My Vessel" garage that is not yet fully profiled in the database, they are prompted to help complete the profile. The process is designed to be simple, guided, and rewarding:

1. The user enters their **Hull Identification Number (HIN)**. A HIN decoder API (e.g., from HINSearchPlus or a custom implementation) automatically pre-fills the manufacturer, model year, and hull serial number.
2. The user is presented with a structured checklist of key equipment categories (Engine, Chartplotter, VHF Radio, Anchor Winch, Bilge Pump, etc.).
3. For each category, they select the make and model from a pre-populated dropdown, or enter it manually if it is not listed.
4. They are invited to upload a photo of their original boat specification sheet, owner's manual, or a photo of the equipment itself.
5. Upon submission, the data enters a **verification queue** for review by our internal team.

**The Incentive:** Upon successful verification and approval of their vessel's complete profile, the user receives **1,000 Crew Points** — equivalent to a $10 discount on their next purchase. This is a highly cost-effective way to acquire high-value data.

### 4.3. Stream 3: Manufacturer & Dealer Partnerships (The Authoritative Source)

This is the long-term strategy to secure the most accurate, authoritative, and comprehensive data, particularly for new model years.

**The Value Proposition for Manufacturers:** We offer participating manufacturers a **"Helm Certified Model"** badge displayed prominently on their model's profile page and within the "My Vessel" feature. This badge signals to users that the data for their boat is verified and authoritative, building trust. In exchange, manufacturers provide us with their official OEM equipment data in whatever format is most convenient for them (spreadsheets, PDFs, database exports).

**The Value Proposition for Dealers:** Major NZ marine dealers (e.g., Bayswater Marine, Haines Hunter NZ) have access to detailed specification data for every boat they sell. A dealer partnership programme would allow them to contribute data in exchange for being listed as a preferred service provider within the platform.

---

## 5. The Database Schema

The database is designed around a core entity — the `model_year` — which links a specific boat model in a specific year to its factory-installed equipment. This mirrors the ACES vehicle configuration database (VCdb) approach.

**Core Tables:**

| Table | Key Fields | Purpose |
|---|---|---|
| `manufacturers` | `id`, `name`, `country`, `website` | Master list of boat builders |
| `boat_models` | `id`, `manufacturer_id`, `name`, `hull_type`, `propulsion_type`, `length_ft`, `beam_in` | Master list of model families |
| `model_years` | `id`, `boat_model_id`, `year`, `brochure_url`, `hin_prefix` | A specific model in a specific year — the primary key for fitment lookups |
| `equipment_categories` | `id`, `name`, `parent_category_id` | Hierarchical categories (e.g., Electronics > Navigation > Chartplotter) |
| `oem_equipment` | `id`, `model_year_id`, `equipment_category_id`, `equipment_make`, `equipment_model`, `part_sku`, `is_standard`, `data_source`, `confidence_score` | The core fitment table — links a model year to its installed equipment |
| `compatible_products` | `id`, `oem_equipment_id`, `product_sku`, `compatibility_type` | Links OEM equipment to our product catalogue (service parts, upgrades, accessories) |

The `confidence_score` field (a float from 0.0 to 1.0) is a critical quality control mechanism. Data sourced directly from manufacturers is scored at 1.0. Verified crowdsourced data is scored at 0.8. Unverified crowdsourced data starts at 0.3 and is promoted upon verification. The platform will only surface recommendations based on data with a confidence score above a configurable threshold (default: 0.7).

---

## 6. The HIN Decoder: The Key to Seamless Onboarding

The **Hull Identification Number (HIN)** is a 12-character alphanumeric code stamped on every production boat, analogous to the VIN on a car. The first three characters are the **Manufacturer Identification Code (MIC)**, assigned by the relevant authority (USCG in the US, Maritime NZ for NZ-built boats). The remaining characters encode the serial number, model year, and date of manufacture.

By integrating a HIN decoder at the point of vessel registration, the platform can:

1. **Automatically identify the manufacturer** from the MIC prefix.
2. **Automatically determine the model year** from the encoded date characters.
3. **Pre-populate the vessel profile** with all known data for that model year, requiring the user only to confirm or correct the details.

This dramatically reduces the friction of adding a vessel to the garage and ensures data consistency across the platform.

---

## 7. The Compounding Value of the Database

The boat OEM database is not merely a feature — it is the foundational data layer that makes the entire Helm platform intelligent. Its value compounds over time in several ways:

**For the customer:** The more complete their vessel profile, the more personalised and useful every interaction with the platform becomes — from product recommendations to service reminders to AI agent responses.

**For the platform:** Every vessel profile added enriches the database. Every purchase made against a vessel profile creates a data point linking a product to a boat type, building a proprietary understanding of what NZ boaters buy and when.

**For the AI agents:** The OEM database is the primary RAG corpus for the domain-specialist AI agents. An agent that knows a customer has a 2022 Stabicraft 2050 Supercab fitted with a Yamaha F150 can provide dramatically more specific, accurate, and useful advice than one working from generic knowledge alone.

**As a competitive moat:** Once built, this database is extremely difficult and expensive for a competitor to replicate. It represents hundreds of thousands of dollars of research investment and years of community contribution. It is, in effect, an unfair advantage.

---

## 8. Phased Rollout Plan

| Phase | Timeline | Scope | Goal |
|---|---|---|---|
| **Phase 1: Foundation** | Months 1–3 | Top 30 NZ models, last 10 years | Cover ~60% of the NZ trailer boat fleet at launch |
| **Phase 2: Crowdsource Launch** | Month 3 | HIN decoder + user contribution flow | Begin scaling the database beyond the curated set |
| **Phase 3: Partnership Programme** | Months 4–6 | Approach Tier 1 manufacturers | Secure authoritative data for new model years |
| **Phase 4: Full Coverage** | Months 6–18 | All Tier 2 and Tier 3 models | Achieve comprehensive coverage of the NZ market |
| **Phase 5: Pacific Expansion** | Months 18+ | Australian, Pacific Island brands | Expand the platform's addressable market |
