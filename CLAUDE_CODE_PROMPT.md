# Helm Marine Platform — Claude Code Development Prompt

**Version:** 1.0 | **Date:** 22 February 2026

---

## Context & Mission

You are the lead developer for **Helm**, New Zealand's most ambitious marine e-commerce platform. Your mission is to build the complete platform from the ground up, following the specifications in the `first_mate` GitHub repository.

**GitHub Repository:** `https://github.com/BalanceNow-ai/first_mate`

Before writing a single line of code, read the following documents in order:

1. `docs/04_technical_spec/Helm_Platform_Full_Specification.md` — **Master specification. Read this first.**
2. `docs/03_product_design/NZ_Marine_Platform_Product_Design.md` — Full product design
3. `docs/03_product_design/RAG_and_Checklist_Design_Specification.md` — AI agent & RAG architecture
4. `docs/03_product_design/Helm_Boat_Database_Design_Specification.md` — Boat OEM database design
5. `docs/03_product_design/Helm_Platform_Feature_Specification_Loyalty_and_Delivery.md` — Crew Rewards & Helm Dash delivery
6. `docs/05_wireframes/index.html` — Open in a browser. This is the definitive UI reference.

---

## 1. Core Technology Stack

### Frontend

| Technology | Purpose | Notes |
|---|---|---|
| **Flutter (latest stable)** | Single codebase for all platforms | Target: iOS, Android, Web, Windows, macOS |
| **flutter_riverpod** | State management | Preferred over Provider or Bloc for this project |
| **go_router** | Navigation | Declarative routing for web-compatible deep linking |
| **dio** | HTTP client | For all API calls to the FastAPI backend |
| **flutter_secure_storage** | Secure token storage | For storing JWT tokens on all platforms |

### Backend

| Technology | Purpose | Notes |
|---|---|---|
| **Python 3.11+** | Backend language | |
| **FastAPI** | API framework | Auto-generates OpenAPI/Swagger docs |
| **SQLAlchemy 2.0** | ORM | Async-first with PostgreSQL |
| **Alembic** | Database migrations | |
| **Pydantic v2** | Data validation | Used throughout FastAPI models |
| **Celery + Redis** | Background task queue | For order processing, email, AI jobs |
| **pytest** | Testing framework | All business logic must have tests |

### Data Layer

| Technology | Purpose | Notes |
|---|---|---|
| **PostgreSQL 16+** | Primary relational database | All transactional and product data |
| **pgvector** | Vector embeddings | RAG corpus for all AI agents, stored in Postgres |
| **Redis** | Cache + Celery broker | Session cache, rate limiting, task queue |
| **Typesense** | Search engine | Product search, autocomplete, faceted filtering |

### AI & Machine Learning

| Technology | Purpose | Notes |
|---|---|---|
| **LangChain** | Agent orchestration | For building the First Mate and domain agents |
| **LlamaIndex** | RAG pipeline | For indexing and querying the knowledge corpus |
| **OpenAI API** | LLM provider | `gpt-4.1-mini` for complex reasoning; `gpt-4.1-nano` for simpler classification tasks |
| **text-embedding-3-small** | Embeddings | For generating vector embeddings of all corpus documents |

### Infrastructure

| Technology | Purpose | Notes |
|---|---|---|
| **Docker + Docker Compose** | Containerisation | All services run in containers |
| **GitHub Actions** | CI/CD | Automated testing and deployment pipeline |
| **AWS or Render.com** | Cloud hosting | Backend API, PostgreSQL, Redis |
| **Cloudflare** | CDN + DDoS protection | For the Flutter web frontend |

---

## 2. Third-Party Integrations

### 2.1 Payments & Financial

#### Stripe (Primary Payment Gateway)
- **Purpose:** All credit/debit card processing, subscription management, and marketplace payments.
- **SDK:** `stripe-python` (backend), `flutter_stripe` (frontend)
- **Implementation:**
  - Use Stripe Payment Intents API for all one-time purchases.
  - Implement Stripe Customer objects for all registered users to enable saved payment methods.
  - Activate **Afterpay/Clearpay** directly within the Stripe Dashboard (no separate API needed). Afterpay is the dominant BNPL provider in NZ.
  - Implement **Stripe Connect** for the Helm Dash partner payout system (paying water taxi operators their share of delivery fees).
  - Store only the Stripe Customer ID in your database. Never store raw card data.
- **Environment Variables:** `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`
- **Webhooks to handle:** `payment_intent.succeeded`, `payment_intent.payment_failed`, `charge.refunded`

#### Laybuy (Secondary BNPL)
- **Purpose:** A second BNPL option. Laybuy is a NZ-founded service that allows 6 weekly instalments.
- **API Docs:** `https://api.laybuy.com/docs`
- **Implementation:** Integrate via their REST API. Redirect the customer to Laybuy's hosted checkout page, then handle the return redirect with the order token.
- **Environment Variables:** `LAYBUY_API_KEY`, `LAYBUY_API_SECRET`, `LAYBUY_SANDBOX` (boolean)

---

### 2.2 Authentication & Identity

#### Supabase Auth
- **Purpose:** User authentication, session management, and social logins.
- **SDK:** `supabase-py` (backend), `supabase_flutter` (frontend)
- **Implementation:**
  - Use Supabase Auth as the identity provider. Your FastAPI backend validates the JWT tokens issued by Supabase.
  - Enable the following social login providers in the Supabase Dashboard: **Google**, **Apple** (required for iOS App Store compliance), **Facebook**.
  - Implement Row Level Security (RLS) policies in Supabase for any data stored directly in Supabase (e.g., user profiles).
  - For data stored in your own PostgreSQL instance, validate the Supabase JWT in FastAPI middleware and extract the `user_id` for all authenticated requests.
- **Environment Variables:** `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`

---

### 2.3 Content Management (Headless CMS)

#### Strapi (Self-Hosted)
- **Purpose:** Manages all non-transactional content: marketing pages, expert guides, blog posts, product descriptions, the Boat OEM Database, and the Experience catalogue for the Crew Rewards programme.
- **Hosting:** Deploy Strapi on a separate Docker container alongside the main backend.
- **Content Types to create in Strapi:**
  - `Article` (for The Boat Ramp content hub: guides, how-tos, fishing reports)
  - `BoatMake` (e.g., Stabicraft, Rayglass)
  - `BoatModel` (linked to `BoatMake`, includes hull type, length, beam)
  - `BoatVariant` (linked to `BoatModel`, includes model year, OEM engine, OEM equipment list)
  - `Experience` (for the Crew Rewards experience catalogue: name, description, images, points cost, availability)
  - `ServiceProvider` (for the service provider directory: name, location, specialties, contact)
- **API Access:** Use Strapi's REST API from the FastAPI backend to fetch content. Cache responses in Redis with a 1-hour TTL.
- **Environment Variables:** `STRAPI_URL`, `STRAPI_API_TOKEN`

---

### 2.4 Search

#### Typesense (Self-Hosted)
- **Purpose:** Powers the product search bar, autocomplete, and faceted category filtering.
- **SDK:** `typesense` (Python), `typesense_dart` (Flutter)
- **Implementation:**
  - Run Typesense in a Docker container.
  - Create a `products` collection in Typesense with the following fields: `id`, `name`, `description`, `brand`, `category`, `sub_category`, `price`, `sku`, `compatible_makes`, `compatible_models`, `compatible_years`, `in_stock` (boolean).
  - Write a Celery task that syncs product data from PostgreSQL to Typesense every 15 minutes, and also triggers an immediate sync on any product update.
  - The Flutter search bar should call Typesense directly (using the Typesense Search-Only API key) for instant, low-latency results.
  - Implement **faceted search** so users can filter by category, brand, price range, and compatibility.
  - When a user has an active vessel in "My Vessel" garage, pass the vessel's make, model, and year as filter parameters to Typesense to show only compatible products.
- **Environment Variables:** `TYPESENSE_HOST`, `TYPESENSE_PORT`, `TYPESENSE_API_KEY`, `TYPESENSE_SEARCH_ONLY_KEY`

---

### 2.5 Shipping & Logistics

#### NZ Post Shipping API
- **Purpose:** Generate shipping labels, calculate rates, and provide tracking for standard courier deliveries.
- **API Docs:** `https://www.nzpost.co.nz/business/ecommerce/shipping-apis`
- **Implementation:**
  - Integrate the **Rate Card API** to calculate shipping costs at checkout based on parcel dimensions, weight, and destination postcode.
  - Integrate the **Label API** to generate a shipping label PDF when an order is fulfilled.
  - Integrate the **Tracking API** to provide customers with real-time parcel tracking. Store the tracking number against the order in PostgreSQL.
- **Environment Variables:** `NZPOST_CLIENT_ID`, `NZPOST_CLIENT_SECRET`, `NZPOST_ACCOUNT_NUMBER`

#### Aramex NZ API
- **Purpose:** Secondary courier for rural and regional deliveries where NZ Post rates are uncompetitive.
- **API Docs:** `https://www.aramex.co.nz/tools/api`
- **Implementation:** Mirror the NZ Post integration pattern. At checkout, call both APIs and display the cheaper rate to the customer.
- **Environment Variables:** `ARAMEX_API_KEY`, `ARAMEX_ACCOUNT_NUMBER`

#### Mapbox (Helm Dash Delivery)
- **Purpose:** The interactive map in the Helm Dash delivery checkout, allowing customers to drop a pin on their vessel's location.
- **SDK:** `mapbox_maps_flutter`
- **Implementation:**
  - Display a nautical-style map centred on the Hauraki Gulf by default.
  - Allow the user to drag a pin to their exact location.
  - Reverse-geocode the coordinates to display a human-readable location name.
  - Calculate the nautical miles from the warehouse to the pin, and display the estimated delivery time.
- **Environment Variables:** `MAPBOX_ACCESS_TOKEN`

---

### 2.6 Analytics & Monitoring

#### PostHog (Self-Hosted or Cloud)
- **Purpose:** Product analytics, user session recording, funnel analysis, A/B testing, and feature flags.
- **SDK:** `posthog-python` (backend), `posthog_flutter` (frontend)
- **Key Events to Track:**
  - `vessel_added` (when a user adds a boat to their garage)
  - `compatibility_filter_toggled`
  - `first_mate_conversation_started`
  - `product_viewed`, `product_added_to_cart`, `checkout_started`, `order_completed`
  - `checklist_item_added_to_cart`
  - `crew_created`, `crew_member_invited`
  - `helm_dash_selected`
- **Environment Variables:** `POSTHOG_API_KEY`, `POSTHOG_HOST`

#### Sentry
- **Purpose:** Error tracking and performance monitoring for both the Flutter frontend and FastAPI backend.
- **SDK:** `sentry-sdk` (Python), `sentry_flutter` (Flutter)
- **Environment Variables:** `SENTRY_DSN`

---

### 2.7 Email & Notifications

#### Resend
- **Purpose:** Transactional email (order confirmations, shipping notifications, service reminders, Crew Rewards updates).
- **SDK:** `resend` (Python)
- **Key Email Templates to build:**
  - Order confirmation
  - Shipping notification with tracking link
  - Service reminder ("Your Yamaha F200 is due for its 100-hour service")
  - Crew Rewards: points earned, multiplier unlocked, experience redeemed
  - Helm Dash: delivery confirmed, skipper en route, delivery completed
- **Environment Variables:** `RESEND_API_KEY`, `RESEND_FROM_EMAIL`

#### Firebase Cloud Messaging (FCM)
- **Purpose:** Push notifications for the mobile app (iOS and Android).
- **SDK:** `firebase_messaging` (Flutter)
- **Key Push Notifications:**
  - Helm Dash delivery status updates
  - Service reminders
  - Crew Rewards milestones
  - Price drop alerts on wishlisted products
- **Environment Variables:** `FIREBASE_SERVER_KEY`, `FIREBASE_PROJECT_ID`

---

### 2.8 Storage

#### AWS S3 (or Cloudflare R2)
- **Purpose:** Storage for all product images, user-uploaded vessel photos, and generated shipping label PDFs.
- **SDK:** `boto3` (Python)
- **Implementation:**
  - All product images uploaded via Strapi are stored in S3.
  - Serve images via a CDN (Cloudflare) for fast global delivery.
  - Use pre-signed URLs for any private user-uploaded content.
- **Environment Variables:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET`, `AWS_REGION`

---

## 3. Database Schema (Key Tables)

```sql
-- Users (managed by Supabase Auth, mirrored here)
CREATE TABLE users (
    id UUID PRIMARY KEY, -- Matches Supabase Auth user ID
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vessels (My Vessel Garage)
CREATE TABLE vessels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    nickname TEXT NOT NULL,
    hin TEXT,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year INTEGER NOT NULL,
    engine_make TEXT,
    engine_model TEXT,
    engine_serial TEXT,
    engine_hours INTEGER,
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Products
CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    brand TEXT,
    category TEXT NOT NULL,
    sub_category TEXT,
    price NUMERIC(10,2) NOT NULL,
    cost_price NUMERIC(10,2),
    stock_quantity INTEGER DEFAULT 0,
    weight_grams INTEGER,
    images JSONB, -- Array of S3 URLs
    specifications JSONB, -- Key-value pairs
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Product Compatibility (links products to vessel makes/models/years)
CREATE TABLE product_compatibility (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE,
    vessel_make TEXT,
    vessel_model TEXT,
    year_from INTEGER,
    year_to INTEGER,
    engine_make TEXT,
    engine_model TEXT,
    notes TEXT
);

-- Orders
CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending', -- pending, paid, fulfilled, shipped, delivered, cancelled
    subtotal NUMERIC(10,2) NOT NULL,
    shipping_cost NUMERIC(10,2) NOT NULL,
    total NUMERIC(10,2) NOT NULL,
    stripe_payment_intent_id TEXT,
    delivery_type TEXT, -- 'courier', 'helm_dash', 'click_and_collect'
    shipping_address JSONB,
    helm_dash_coordinates JSONB, -- {lat, lng} for water delivery
    tracking_number TEXT,
    courier TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Order Items
CREATE TABLE order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
    product_id UUID REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL
);

-- Crew Rewards
CREATE TABLE crew_points (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    points_balance INTEGER DEFAULT 0,
    tier TEXT DEFAULT 'deckhand', -- deckhand, mate, skipper, captain
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE crew_teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE crew_team_members (
    team_id UUID REFERENCES crew_teams(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (team_id, user_id)
);

-- AI Agent Conversations
CREATE TABLE ai_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    vessel_id UUID REFERENCES vessels(id),
    messages JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- RAG Vector Store (pgvector)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_domain TEXT NOT NULL, -- 'engine', 'electrical', 'game_fishing', etc.
    source TEXT NOT NULL, -- URL or filename of the source document
    content TEXT NOT NULL,
    embedding vector(1536), -- text-embedding-3-small dimensions
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON rag_documents USING ivfflat (embedding vector_cosine_ops);
```

---

## 4. API Structure (FastAPI)

Organise the FastAPI application into the following routers:

```
/api/v1/
├── /auth/           -- Login, register, refresh token (delegates to Supabase)
├── /users/          -- User profile management
├── /vessels/        -- CRUD for My Vessel Garage
├── /products/       -- Product catalogue, compatibility filtering
├── /search/         -- Search endpoint (proxies to Typesense with auth)
├── /cart/           -- Shopping cart management
├── /orders/         -- Order creation, history, tracking
├── /payments/       -- Stripe payment intents, webhooks
├── /shipping/       -- Rate calculation (NZ Post + Aramex)
├── /ai/             -- First Mate chat endpoint, conversation history
├── /checklists/     -- Voyage checklist generation and management
├── /loyalty/        -- Crew points, team management, experience redemption
├── /helm-dash/      -- Helm Dash delivery management
├── /content/        -- Proxy to Strapi CMS for articles, guides
└── /admin/          -- Admin endpoints (order management, product management)
```

---

## 5. AI Agent Architecture

### The First Mate (Orchestrator Agent)

The First Mate is the only agent the user interacts with directly. It is a LangChain agent with the following tools available:

```python
tools = [
    VesselContextTool(),       # Retrieves the user's active vessel details
    ProductSearchTool(),       # Searches the product catalogue via Typesense
    EngineProTool(),           # Delegates to the Engine & Propulsion domain agent
    ElectricalSageTool(),      # Delegates to the Electrical & Solar domain agent
    PlumbingProTool(),         # Delegates to the Plumbing & Pumps domain agent
    GalleyGuruTool(),          # Delegates to the Galley & Cabin domain agent
    GameFishingExpertTool(),   # Delegates to the Game Fishing domain agent
    AnchoringMasterTool(),     # Delegates to the Anchoring & Mooring domain agent
    SafetyOfficerTool(),       # Delegates to the Safety & Compliance domain agent
    RiggingSpecialistTool(),   # Delegates to the Rigging & Deck domain agent
    ElectronicsTool(),         # Delegates to the Electronics & Navigation domain agent
    ChecklistTool(),           # Generates or updates voyage checklists
    ServiceReminderTool(),     # Checks and updates service schedule
    ServiceProviderTool(),     # Recommends local marine service providers
    AddToCartTool(),           # Adds a product to the user's cart
    OrderHistoryTool(),        # Retrieves the user's order history
]
```

### Domain Agent RAG Corpus Sources

Each domain agent has its own RAG corpus, indexed in pgvector with the `agent_domain` field set accordingly. Populate each corpus from the following sources:

| Domain | `agent_domain` value | Corpus Sources |
|---|---|---|
| Engine & Propulsion | `engine` | Yamaha, Mercury, Suzuki, Honda, Evinrude service manuals; NGK spark plug guides; impeller replacement guides |
| Electrical & Solar | `electrical` | ABYC electrical standards; Victron Energy documentation; Blue Sea Systems guides; 12V wiring guides |
| Plumbing & Pumps | `plumbing` | Rule Industries pump guides; Jabsco service manuals; marine sanitation guides; hose sizing charts |
| Galley & Cabin | `galley` | Dometic product manuals; Force 10 stove guides; watermaker installation guides |
| Game Fishing | `game_fishing` | IGFA rules; NZ game fishing regulations; marlin/tuna rigging guides; NZGFA publications |
| Anchoring & Mooring | `anchoring` | Rocna anchor sizing guides; chain sizing charts; windlass installation guides |
| Safety & Compliance | `safety` | Maritime NZ safety regulations; EPIRB registration guides; life raft service schedules; NZ distress signal rules |
| Rigging & Deck | `rigging` | Selden rigging guides; Harken block selection guides; furling system manuals |
| Electronics & Nav | `electronics` | Garmin/Simrad/Navionics documentation; AIS setup guides; VHF radio guides |
| Trailer & Towing | `trailer` | NZ trailer regulations; bearing maintenance guides; brake controller guides |
| Fishing Tackle | `fishing` | NZ fishing regulations; species guides; softbait rigging guides; knot guides |
| Boat OEM | `boat_oem` | All content from the Boat OEM Database in Strapi (make/model/year/equipment data) |

---

## 6. Environment Variables Reference

Create a `.env` file (never commit this to GitHub — add to `.gitignore`). Use a `.env.example` file with all keys listed but no values.

```env
# Application
APP_ENV=development
SECRET_KEY=<generate a 64-char random string>
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080

# Database
DATABASE_URL=postgresql+asyncpg://helm:password@localhost:5432/helm_db
REDIS_URL=redis://localhost:6379/0

# Supabase Auth
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Laybuy
LAYBUY_API_KEY=
LAYBUY_API_SECRET=
LAYBUY_SANDBOX=true

# Strapi CMS
STRAPI_URL=http://localhost:1337
STRAPI_API_TOKEN=

# Typesense
TYPESENSE_HOST=localhost
TYPESENSE_PORT=8108
TYPESENSE_API_KEY=
TYPESENSE_SEARCH_ONLY_KEY=

# NZ Post
NZPOST_CLIENT_ID=
NZPOST_CLIENT_SECRET=
NZPOST_ACCOUNT_NUMBER=

# Aramex NZ
ARAMEX_API_KEY=
ARAMEX_ACCOUNT_NUMBER=

# Mapbox
MAPBOX_ACCESS_TOKEN=

# OpenAI
OPENAI_API_KEY=

# AWS S3
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_S3_BUCKET=helm-marine-assets
AWS_REGION=ap-southeast-2

# Email (Resend)
RESEND_API_KEY=
RESEND_FROM_EMAIL=noreply@helmmarine.co.nz

# Firebase (Push Notifications)
FIREBASE_SERVER_KEY=
FIREBASE_PROJECT_ID=

# Analytics
POSTHOG_API_KEY=
POSTHOG_HOST=https://app.posthog.com

# Error Tracking
SENTRY_DSN=
```

---

## 7. Development Workflow

Follow this recursive, AI-reviewed process for every phase:

1. **Read the spec** for the current phase from the `first_mate` repository.
2. **Write tests first (TDD):** Create failing tests that define the expected behaviour.
3. **Implement the feature** until all tests pass.
4. **Commit directly to `main`** on `https://github.com/BalanceNow-ai/first_mate`. Do not use pull requests.
5. **Request a Manus review** via the Manus API. Ask: *"Please review the code committed to the first_mate repository for Phase [X]. Assess quality, accuracy to the specification in docs/04_technical_spec/, and completeness. List specific issues to fix before I continue."*
6. **Implement all feedback** from the Manus review.
7. **Repeat steps 5–6** until Manus approves the phase.
8. **Proceed to the next phase.**

---

## 8. Non-Functional Requirements

- **Performance:** All API endpoints must respond in under 200ms at the 95th percentile. Product search must return results in under 100ms.
- **Security:** All API endpoints (except public product catalogue and auth) require a valid Supabase JWT. Implement rate limiting on all endpoints. Never log sensitive data (card numbers, passwords, API keys).
- **Accessibility:** The Flutter UI must meet WCAG 2.1 AA standards.
- **Internationalisation:** The platform is NZ-English only at launch. All prices are in NZD.
- **Testing:** Minimum 80% code coverage on all backend business logic. All critical user flows (add to cart, checkout, vessel registration, AI chat) must have end-to-end tests.
- **Documentation:** All FastAPI endpoints must have complete docstrings. The auto-generated Swagger UI at `/docs` must be accurate and complete.

---

*This prompt, together with the specification documents in the `first_mate` repository, constitutes the complete development brief for the Helm platform.*
