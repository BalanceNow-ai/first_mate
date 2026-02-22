# Helm Platform: Production Boat Database Design Specification

**Prepared by Manus AI | February 2026**

---

## 1. Executive Summary

To power the "My Vessel" garage and deliver a truly personalised, intelligent user experience, a comprehensive database of production boat models and their factory-installed Original Equipment Manufacturer (OEM) equipment is required. Research confirms that no single, publicly available database exists for the marine industry that is equivalent to the ACES/PIES standard in the automotive sector. Commercial offerings like TheBoatDB, ABOS Marine Blue Book, and MarineLink provide high-level specifications but lack the granular, model-year-specific OEM equipment data needed.

Therefore, this document outlines a strategy to **build a proprietary, NZ-focused boat database**. This strategy is based on a multi-pronged data acquisition model that combines manual curation, user crowdsourcing, and long-term industry partnerships. This database will become a core intellectual property asset and a significant competitive advantage.

---

## 2. The Data Acquisition Strategy: A Three-Pronged Approach

Since no single source of truth exists, we must create it. The strategy relies on three concurrent streams of data acquisition.

### 2.1. Phase 1: Manual Curation (The Foundation)

The initial database will be built by a dedicated internal team focusing on the highest-value models first.

*   **Target:** The top 30 most popular production trailer boats sold in New Zealand over the last 15 years (e.g., Stabicraft 1550/2050, Haines Hunter SF545, Rayglass Legend 2200, Quintrex Fishabout).
*   **Process:** This is a manual research and data entry task. The team will gather official manufacturer brochures, specification sheets, boat reviews from magazines (e.g., NZ Fishing World, Boating NZ), and YouTube video walkthroughs for each model year.
*   **Outcome:** A high-quality, foundational dataset covering the most common boats owned by our target customers. This ensures the "My Vessel" feature provides immediate value to a significant portion of the user base at launch.

### 2.2. Phase 2: Crowdsourcing & Gamification (The Scale Engine)

To scale the database beyond the initial curated set, we will leverage our user base.

*   **Mechanism:** When a user adds a vessel to their "My Vessel" garage that is not yet fully profiled in our database, they will be prompted to help complete the profile.
*   **User Flow:**
    1.  The user enters their Hull Identification Number (HIN). A HIN decoder API pre-fills the manufacturer, model year, and hull number.
    2.  The user is presented with a list of key equipment categories (e.g., Engine, Chartplotter, VHF Radio, Anchor Winch, Bilge Pump).
    3.  For each category, they can select the make and model from a dropdown (pre-populated with common brands) or enter it manually.
    4.  They can upload a photo of their original boat specification sheet or owner's manual.
*   **Incentive:** Upon successful completion of their vessel's profile (verified by our team), the user is rewarded with **1,000 Crew Points**. This gamifies the process and provides a tangible reward for their contribution.

### 2.3. Phase 3: Industry Partnerships (The Authoritative Source)

This is a long-term strategy to secure the most accurate and comprehensive data.

*   **Target:** New Zealand's leading boat manufacturers (e.g., Stabicraft, Rayglass, Haines Hunter) and major dealerships.
*   **Value Proposition:** We offer manufacturers a "Helm Certified Model" badge on our platform. In exchange for providing detailed OEM equipment lists for their new and past models, their boats will be highlighted in search results and within the "My Vessel" feature, signalling a higher level of data quality and trust to potential buyers.
*   **Data Format:** We will work with manufacturers to accept data in whatever format is easiest for them (e.g., spreadsheets, internal database exports) and handle the mapping to our schema internally.

---

## 3. Database Schema Design

The database will be structured to link boats to their specific factory-installed equipment. The proposed schema is as follows:

**Table: `manufacturers`**
| Column | Type | Description |
|---|---|---|
| `id` | `INT` (PK) | Unique identifier for the manufacturer. |
| `name` | `VARCHAR` | e.g., "Stabicraft Marine Ltd" |
| `country_of_origin` | `VARCHAR` | e.g., "New Zealand" |

**Table: `boat_models`**
| Column | Type | Description |
|---|---|---|
| `id` | `INT` (PK) | Unique identifier for the model. |
| `manufacturer_id` | `INT` (FK) | Links to `manufacturers.id`. |
| `name` | `VARCHAR` | e.g., "2250 Ultracab WT" |
| `length_ft` | `DECIMAL` | Overall length in feet. |
| `beam_in` | `DECIMAL` | Beam width in inches. |
| `hull_type` | `ENUM` | ('Monohull', 'Catamaran', 'Trimaran') |
| `propulsion_type` | `ENUM` | ('Outboard', 'Inboard', 'Sterndrive', 'Jet') |

**Table: `model_years`**
| Column | Type | Description |
|---|---|---|
| `id` | `INT` (PK) | Unique identifier for a specific model year. |
| `boat_model_id` | `INT` (FK) | Links to `boat_models.id`. |
| `year` | `INT` | The model year, e.g., 2024. |
| `brochure_url` | `VARCHAR` | Link to the official PDF brochure. |

**Table: `equipment_categories`**
| Column | Type | Description |
|---|---|---|
| `id` | `INT` (PK) | Unique identifier for the category. |
| `name` | `VARCHAR` | e.g., "Engine", "Chartplotter", "VHF Radio" |

**Table: `oem_equipment`** (The core of the database)
| Column | Type | Description |
|---|---|---|
| `id` | `INT` (PK) | Unique identifier for the equipment record. |
| `model_year_id` | `INT` (FK) | Links to `model_years.id`. |
| `equipment_category_id` | `INT` (FK) | Links to `equipment_categories.id`. |
| `part_sku` | `VARCHAR` | Our internal product SKU (if we sell it). |
| `equipment_make` | `VARCHAR` | e.g., "Yamaha", "Simrad", "GME" |
| `equipment_model` | `VARCHAR` | e.g., "F200XCA", "NSS12 Evo3", "GX700" |
| `is_standard` | `BOOLEAN` | `TRUE` if standard fitment, `FALSE` if optional. |
| `data_source` | `ENUM` | ('Manufacturer', 'Curation', 'Crowdsource') |
| `confidence_score` | `FLOAT` | A score from 0.0 to 1.0 indicating data reliability. |

---

## 4. Maintenance & Verification Model

A database is only as good as its accuracy. A robust maintenance and verification process is essential.

*   **Verification Queue:** All crowdsourced data submissions will enter a verification queue.
*   **Internal Review:** The internal data curation team will review each submission, comparing it against other sources (e.g., other user submissions for the same model, online forums, photos) before approving it.
*   **Confidence Scoring:** The `confidence_score` will be used to manage data quality. Data from manufacturers gets a score of 1.0. Verified crowdsourced data might get 0.8. Unverified data starts at 0.3. This allows the platform to, for example, only show recommendations based on data with a confidence score > 0.7.
*   **Continuous Improvement:** The database is a living asset. As new models are released and more users contribute data, its accuracy and value will compound over time, creating a powerful and defensible moat for the business.
