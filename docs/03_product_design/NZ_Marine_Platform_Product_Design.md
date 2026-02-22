# Product Design & Feature Specification
## A World-Class B2C Marine Parts & Fishing Equipment Platform for New Zealand

**Author:** Manus AI | **Date:** February 2026 | **Version:** 1.0

---

## 1. Vision & Strategic Intent

The New Zealand marine and fishing retail market is served by a handful of established players — Marine Deals, Burnsco, and Smart Marine — that have built their online presence as digital extensions of a traditional retail model. They are competent e-commerce stores, but they are fundamentally **catalogues with a checkout**. They do not know your boat. They do not remember what you bought last season. They cannot tell you whether a part will fit your engine, guide you through an installation, or remind you that your flares expire next month.

This platform is designed to be something categorically different: **the indispensable digital partner for every Kiwi boat owner and fishing enthusiast.** It will combine the best e-commerce features of the world's leading parts retailers with a pioneering AI architecture that makes every customer interaction smarter, more relevant, and more valuable than anything available in the New Zealand market today.

The platform's working name is **"Helm"** — the place from which you navigate everything.

---

## 2. Competitive Audit: The Gap in the Market

A direct audit of the three primary NZ competitors reveals a consistent and exploitable set of weaknesses.

| Feature | Marine Deals | Burnsco | Smart Marine | **Helm** |
|---|:---:|:---:|:---:|:---:|
| Vessel Profile ("My Vessel") | No | No | No | **Yes** |
| Engine-Level Fitment Filtering | No | No | No | **Yes** |
| Interactive OEM Parts Diagrams | No | No | No | **Yes** |
| AI-Powered Search & Discovery | No | No | No | **Yes** |
| Domain-Specialist AI Agents | No | No | No | **Yes** |
| Personalised Customer AI Agent | No | No | No | **Yes** |
| Predictive Maintenance Reminders | No | No | No | **Yes** |
| NZ Fishing Reports & Local Knowledge | No | No | No | **Yes** |
| Service Provider Directory | No | No | No | **Yes** |
| NZ Regulatory & Safety Centre | No | No | No | **Yes** |
| Community Forum | No | No | No | **Yes** |
| Expert Video Content | No | No | No | **Yes** |
| Price Match Guarantee | Yes | Yes | Yes | **Yes** |
| AfterPay / Laybuy | Yes | Yes | Yes | **Yes** |
| Click & Collect | Yes | Yes | Yes | **Yes** |

The table above illustrates that the competitive advantage is not in matching what already exists — it is in introducing an entirely new category of value that the incumbents are structurally unable to replicate quickly.

---

## 3. Core E-Commerce Features (The Foundation)

Before any AI layer, the platform must execute flawlessly on the fundamentals. These are the non-negotiable requirements for a world-class e-commerce experience.

### 3.1 Search & Discovery

The search experience is the most critical UX element on a parts website. The platform will implement a multi-modal search architecture:

**Keyword & Part Number Search** must be fast, forgiving of typos, and capable of matching against product names, descriptions, SKUs, OEM part numbers, and cross-reference numbers. Autocomplete suggestions should appear within 150ms. **Natural Language Search** will allow customers to type queries like "waterproof VHF radio for a small runabout" and receive intelligently ranked results. **Visual Search** will allow users to photograph a part and find it in the catalogue. **Vessel-Scoped Search** means that when a customer has a vessel selected in their profile, all search results are automatically filtered to show only compatible products, with incompatible items either hidden or clearly flagged.

### 3.2 Navigation & Information Architecture

The navigation must serve two distinct user types: the customer who knows exactly what they want (part number search) and the customer who is browsing or exploring (category navigation). The information architecture will be organised around two parallel hierarchies:

The **Category Hierarchy** reflects how parts are used on a boat (e.g., Deck & Hull → Hatches & Ports → Deck Hatches), while the **Brand Hierarchy** allows brand-loyal customers to browse by manufacturer. Both hierarchies will be accessible from a persistent mega-menu.

### 3.3 Product Pages

Each product page will include: multiple high-resolution images with zoom capability; a 360-degree view for complex parts; a short product video where available; full specifications in a structured, scannable format; OEM cross-reference numbers; a clear compatibility statement ("Fits: [list of vessels/engines]"); stock availability (online and per-store); verified customer reviews with photos; and a "Frequently Bought Together" section powered by purchase data.

### 3.4 Checkout & Payment

The checkout will be a streamlined, three-step process (Cart → Details → Payment) with guest checkout available. Payment options will include all major credit/debit cards, PayPal, AfterPay, Laybuy, and bank transfer for large orders. A **Trade Account** option will offer net-30 payment terms for qualified marine businesses.

### 3.5 Fulfilment & Logistics

The platform will offer same-day dispatch for orders placed before 2pm, with NZ-wide courier delivery and rural delivery. **Click & Collect** will be available from a physical location. A **Freight Calculator** will display accurate shipping costs on the product page and in the cart, with no surprise charges at checkout. Free shipping will apply to orders over a defined threshold.

---

## 4. The "My Vessel" Garage

This is the cornerstone feature of the personalised experience and the primary differentiator from every NZ competitor. It is the mechanism through which the platform learns about each customer's boat and filters the entire experience accordingly.

### 4.1 Vessel Profile Setup

During account creation, users are invited (but not required) to add their vessel. The setup wizard is conversational and simple, asking for:

- **Vessel Details:** Name, make (e.g., Stabicraft, Haines Hunter, Riviera), model, year, length, hull type (aluminium, fibreglass, inflatable), and primary use (inshore fishing, offshore fishing, cruising, sailing).
- **Engine Details:** Make (e.g., Yamaha, Mercury, Suzuki, Yanmar), model, year, serial number, and hours. Users with twin engines can add both.
- **Onboard Systems:** A checklist of installed systems that the user can tick off: chartplotter (with model), VHF radio, autopilot, bilge pump, anchor winch, generator, inverter, solar panels, battery system type, toilet type (manual, electric, composting), and galley appliances.
- **Registration & Safety:** NZ boat registration number, EPIRB registration number, and lifejacket count and type.

Multiple vessels can be saved to a single account, with a simple toggle to switch between them. This is particularly valuable for families, fishing clubs, and marine businesses managing a fleet.

### 4.2 Vessel-Driven Personalisation

Once a vessel is saved, it transforms the entire site experience:

The **homepage** displays a "For Your [Vessel Name]" section with relevant new products, current deals, and proactive alerts. The **search results** and **category pages** are automatically scoped to compatible products. **Product pages** display a clear "Fits Your [Vessel Name]" or "Incompatible with Your Vessel" badge. The **First Mate AI Agent** (described in Section 6) uses the vessel profile as its primary context for all interactions.

---

## 5. Interactive OEM Parts Diagrams

This feature directly addresses the most frustrating challenge in marine parts retail: finding the exact right part for a specific engine or piece of equipment.

### 5.1 The Diagram Library

In partnership with major marine equipment manufacturers, the platform will build a comprehensive library of interactive, exploded-view OEM parts diagrams. The initial library will prioritise the most common outboard engine brands in New Zealand (Yamaha, Mercury, Suzuki, Tohatsu, Honda) and expand to include inboard engines (Yanmar, Volvo Penta), anchor winches, marine toilets, and other complex assemblies.

### 5.2 User Experience

A customer navigating to the "Engine Parts" section selects their engine brand, then model, then year. They are presented with a list of sub-assemblies (e.g., "Powerhead," "Lower Unit," "Fuel System"). Selecting a sub-assembly reveals an interactive, zoomable exploded-view diagram. Hovering over any component highlights it and displays its part number and name. Clicking on a component opens a side panel with the product details, price, and stock availability, with an "Add to Cart" button. This transforms a potentially hour-long search into a two-minute task.

---

## 6. The AI Architecture: A Dual-Agent Model

The platform's intelligence is delivered through two complementary types of AI agents, working in concert to provide an experience that is simultaneously deeply knowledgeable and deeply personal.

### 6.1 Architectural Overview

```
Customer Query
      │
      ▼
 First Mate AI (Personal Agent)
 ┌─────────────────────────────┐
 │  Customer RAG Corpus        │
 │  - Vessel Profile(s)        │
 │  - Purchase History         │
 │  - Projects & Wishlists     │
 │  - Conversation History     │
 │  - Browsing Behaviour       │
 └─────────────────────────────┘
      │
      │  Routes to specialist(s) with personal context
      ▼
 Domain-Specialist Agents (Category Experts)
 ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
 │ Pumps &  │ │  Galley  │ │ Game     │ │Electrical│ │ Fenders  │
 │Plumbing  │ │  Agent   │ │ Fishing  │ │& Solar   │ │& Anchors │
 └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
      │              │           │            │             │
      └──────────────┴───────────┴────────────┴─────────────┘
                                 │
                                 ▼
                    Domain RAG Corpuses
                    - Product Manuals
                    - Installation Guides
                    - Manufacturer Knowledge Bases
                    - NZ Regulations & Standards
                    - Expert Articles & Forum Posts
                    - Fishing Reports & Local Knowledge
```

### 6.2 Domain-Specialist AI Agents

Each specialist agent is an expert in its domain, powered by a curated and continuously updated RAG corpus. The initial suite of agents and their domains are:

| Agent Name | Domain | RAG Corpus Contents |
|---|---|---|
| **Pumps & Plumbing Pro** | Bilge pumps, water pumps, sanitation systems, hose, fittings | Jabsco, Rule, Whale, Tru Design manuals; AS/NZS 1546 (sanitation); installation guides |
| **Galley Guru** | Marine stoves, fridges, sinks, gas systems, water makers | Dometic, Webasto, Force 10 manuals; AS/NZS 5601 (gas); NZ gasfitting regulations |
| **Electronics Expert** | Chartplotters, VHF radios, AIS, radar, autopilots, sonar | Garmin, Simrad, Raymarine, Standard Horizon manuals; Maritime NZ radio licensing |
| **Electrical & Solar Sage** | 12V/24V systems, batteries, inverters, solar panels, LED lighting | Victron, Mastervolt, CTEK documentation; ABYC E-11 wiring standards |
| **Rigging & Deck Specialist** | Sails, lines, blocks, winches, hatches, stanchions, fenders | Ronstan, Harken, Lewmar manuals; sailing technique guides |
| **Anchoring & Mooring Master** | Anchors, chain, windlasses, mooring lines, shackles | Maxwell, Lofrans manuals; NZ anchoring regulations; seabed type guides |
| **Safety & Compliance Officer** | Lifejackets, EPIRBs, flares, fire extinguishers, first aid | Maritime NZ regulations; SOLAS standards; lifejacket service schedules |
| **Game Fishing Guide** | Rods, reels, lures, traces, fighting chairs, outriggers | IGFA rules; NZ game fishing regulations; species-specific techniques; local knowledge |
| **Soft Bait & Inshore Specialist** | Soft baits, jigs, light tackle, kayak fishing | NZ inshore species guides; regional fishing reports; technique articles |
| **Trailer & Towing Advisor** | Boat trailers, winches, rollers, bunks, wheel bearings | NZ trailer regulations (NZTA); maintenance guides; towing capacity information |
| **Antifouling & Maintenance Pro** | Antifouling paints, hull cleaners, teak care, engine maintenance | Altex, International Paint guides; NZ biosecurity requirements (clean hull) |
| **Navigation & Regulations Advisor** | Charts, navigation rules, Maritime NZ compliance | Maritime NZ rules; NZ Coastal Pilot; Hydrographic Office chart updates |

**Scalability:** New specialist agents can be spun up as required by creating a new RAG corpus and configuring the routing logic. This is a key architectural advantage — the platform's intelligence grows over time without requiring a full redevelopment.

---

## 7. The "First Mate" Personalised Customer AI Agent

This is the platform's most innovative and commercially significant feature. Every signed-in customer receives a dedicated AI agent — their **First Mate** — that builds a private, evolving understanding of that specific customer.

### 7.1 The Customer RAG Corpus

The First Mate AI's effectiveness is directly proportional to the richness of its private RAG corpus. This corpus is built from two sources:

**Explicit Data** (information the customer consciously provides) includes all vessel profiles from the "My Vessel" garage; project lists and their contents; stated fishing preferences (target species, preferred techniques, usual locations); self-assessed skill level; wishlists and saved items; and any information shared directly in conversation with the agent.

**Implicit Data** (information inferred from behaviour) includes the complete purchase and order history; browsing and product view history; search query history; articles and videos consumed; and conversation logs with the agent and specialist agents.

### 7.2 First Mate Capabilities: A Comprehensive Inventory

The First Mate AI's capabilities span six functional domains:

**Domain 1: Proactive Maintenance & Safety Management**

The First Mate is the customer's proactive maintenance manager. Based on the engine model and hours logged in the vessel profile, it generates a personalised service schedule and sends proactive alerts: *"Hi [Name], your Yamaha F150 is approaching 100 hours — time for an oil and filter change. I've put the correct Yamalube 10W-30, oil filter, and fuel filter into a temporary cart for you. Here's the service manual section for that job."* For safety equipment, it tracks expiry dates and service intervals: *"Your flare kit expires in 6 weeks. Here are the current Maritime NZ-compliant kits. I've also noticed your EPIRB registration is due for renewal — here's the Maritime NZ link."*

**Domain 2: Conversational Troubleshooting & Technical Support**

The First Mate is the customer's first port of call when something goes wrong. A customer can describe a problem in plain English, and the agent uses its knowledge of the customer's specific vessel and equipment to provide targeted diagnostic guidance. *"My bilge pump keeps cycling on and off"* triggers a response that acknowledges the customer's specific pump model (from purchase history), explains the most likely causes (leaky skin fitting, faulty float switch), provides a step-by-step diagnostic process, and links to the relevant products if a replacement is needed. This dramatically reduces the need for human customer service intervention and provides a far superior experience.

**Domain 3: Project Planning & Product Bundling**

When a customer creates a project (e.g., "Galley Upgrade 2026"), the First Mate becomes their project manager. It proactively suggests a complete list of products required for the project — not just the headline item but all the ancillary components, consumables, and tools. It groups items by installation sequence, creates a total budget estimate, and generates a checklist of tasks. For complex projects, it identifies tasks that require professional installation and links to relevant service providers in the directory.

**Domain 4: Intelligent Trip & Fishing Planning**

The First Mate integrates with weather, tide, and community fishing report data to provide personalised trip planning assistance. *"I'm planning a game fishing trip out of Whitianga next Saturday"* prompts the agent to check the marine forecast, consult recent fishing reports from the community hub, review the customer's tackle inventory (inferred from purchase history), and provide a comprehensive briefing: *"The forecast is for 15-knot northeasterlies — manageable but bring your sea anchor. The marlin have been running 30 miles east of the Mercury Islands. Based on your gear, I'd recommend your Shimano Tiagra 50s with 80lb braid. You're running low on Pakula lures — here are the ones that have been working well in recent reports."*

**Domain 5: Regulatory Compliance & Local Knowledge**

The First Mate is the customer's guide to navigating the complex regulatory environment of boating in New Zealand. It can answer questions about anchoring rules, marine reserve boundaries, speed restrictions, safety equipment requirements, and biosecurity obligations (e.g., clean hull requirements for moving between regions). It proactively alerts customers to relevant regulatory changes and links to the NZ Regulatory & Safety Centre for detailed guidance.

**Domain 6: Financial & Ownership Intelligence**

Over time, the First Mate builds a comprehensive picture of the customer's investment in their vessel. It can generate a **Total Cost of Ownership** report, tracking all purchases and maintenance costs. It can help customers **budget for upcoming projects** by providing accurate cost estimates based on real product prices. For customers considering selling their vessel, it can provide a **Maintenance & Upgrade History** report — a valuable document for prospective buyers. It can also alert customers to **price drops** on wishlisted items and **notify them of deals** on products relevant to their vessel and projects.

### 7.3 Additional First Mate Capabilities

Beyond the six core domains, the First Mate can also:

- **Manage a Digital Logbook:** Recording trips, catches, fuel consumption, and maintenance events, with automatic entries created from purchase history.
- **Facilitate Community Connections:** Connecting customers with other owners of the same vessel type, or with fishing club members in their region.
- **Provide Resale & Upgrade Advice:** Advising on which upgrades add the most value to a vessel of that type and age, based on market data.
- **Onboard New Vessel Owners:** When a customer adds a new vessel, the First Mate proactively creates a "New Boat Checklist" of essential safety gear, recommended first upgrades, and common maintenance items for that specific make and model.
- **Handle Returns & Warranty Claims:** Guiding customers through the returns process, pre-populating forms with order details, and tracking the status of claims.
- **Provide Installation Confidence Scoring:** For any product, the agent can assess whether the installation is within the customer's stated skill level and either provide a DIY guide or recommend a professional installer.

---

## 8. Content & Community Hub: "The Boat Ramp"

The platform's content strategy transforms it from a store into a resource, building organic search authority and deep customer loyalty.

### 8.1 Expert Guides & Video Library

A library of professionally produced, NZ-specific content covering installation tutorials, maintenance how-tos, fishing technique guides, and gear reviews. Content is tagged to products, so a customer reading a guide on installing a solar panel system sees the relevant products embedded in the article. Video content is produced in partnership with NZ marine experts, professional skippers, and fishing guides.

### 8.2 NZ Fishing Reports & Local Knowledge

A dedicated section aggregating fishing reports from around New Zealand, contributed by the community and curated by local experts. Reports are tagged by region, species, and technique. This section integrates with the First Mate AI, which uses the reports as a data source for trip planning recommendations.

### 8.3 Community Forum

An integrated forum where customers can ask questions, share project photos, post fishing reports, and connect with fellow enthusiasts. Forum threads are indexed by the domain-specialist agents, meaning that the collective wisdom of the community becomes part of the platform's knowledge base over time. This creates a powerful flywheel: more community content makes the AI agents smarter, which makes the platform more valuable, which attracts more community members.

### 8.4 Service Provider Directory

A curated, rated, and verified directory of qualified marine service providers across New Zealand, including:

- **Marine Mechanics & Engine Specialists** (by engine brand)
- **Marine Electricians** (certified to ABYC or equivalent standards)
- **Boat Builders & Repairers** (fibreglass, aluminium, timber)
- **Riggers & Sailmakers**
- **Marine Surveyors**
- **Trailer Repairers & WOF Inspectors**
- **Lifejacket Service Agents**

Service providers can claim their listing, respond to reviews, and receive referrals from the First Mate AI. This creates a two-sided marketplace that adds significant value to the platform beyond parts retail.

### 8.5 NZ Regulatory & Safety Centre

A comprehensive, plain-English resource covering all aspects of boating law and safety in New Zealand:

- Maritime NZ rules and regulations (by vessel size and type)
- Safety equipment requirements and expiry schedules
- Regional council bylaws (speed limits, anchoring restrictions, marine reserves)
- Biosecurity requirements (clean hull, no fouling organisms)
- Licensing and certification requirements (skipper's ticket, radio operator's certificate)
- Emergency procedures and distress signal protocols

This content is maintained and updated by a qualified maritime professional and is linked directly from relevant product pages and proactively surfaced by the First Mate AI.

---

## 9. Trust, Pricing & Commercial Features

### 9.1 Price Promise

A transparent price-match guarantee: if a customer finds the same product at a lower price from a NZ-based competitor, the platform will match it. The process is streamlined — customers can submit a price-match request directly from the product page.

### 9.2 Loyalty Programme: "The Crew"

A tiered loyalty programme that rewards repeat customers:

| Tier | Annual Spend | Benefits |
|---|---|---|
| **Deckhand** | $0–$499 | 1% cashback on all purchases; access to member-only deals |
| **Mate** | $500–$1,999 | 2% cashback; early access to sales; free standard shipping on all orders |
| **Skipper** | $2,000–$4,999 | 3% cashback; dedicated customer service line; priority order processing |
| **Captain** | $5,000+ | 4% cashback; exclusive product launches; annual gift; personal account manager |

### 9.3 Trade Accounts

A dedicated trade programme for marine businesses (dealers, charter operators, boat yards, fishing lodges) offering:

- Net-30 payment terms
- Volume pricing
- Dedicated account manager
- API access for inventory integration

### 9.4 Financing & BNPL

AfterPay, Laybuy, and Zip Pay for purchases up to $2,000. For larger purchases (e.g., major electronics, anchor winches), a finance option through a NZ finance partner.

---

## 10. Technology Architecture Considerations

### 10.1 E-Commerce Platform

The platform should be built on a modern, headless commerce architecture (e.g., Shopify Plus with a custom Next.js frontend, or a purpose-built solution) to provide the flexibility required for the custom AI and personalisation features. A monolithic platform will not provide the necessary extensibility.

### 10.2 AI & RAG Infrastructure

The AI layer will be built using an **Agentic RAG** architecture, leveraging frameworks such as LangGraph or LlamaIndex for agent orchestration. The vector database for the RAG corpuses (both domain and per-customer) will be a purpose-built solution such as Pinecone, Weaviate, or pgvector. The underlying LLM will be a leading model (e.g., GPT-4.1, Gemini 2.5 Flash) accessed via API, with the ability to swap models as the market evolves.

**Per-Customer RAG Corpus Management:** Each customer's corpus is a private, isolated vector store. As the customer interacts with the platform, new data is continuously ingested and embedded. The corpus is designed to be **transparent and user-controllable** — customers can view what their agent "knows" about them, add information manually, and delete data they do not want stored.

### 10.3 Data & Privacy

All customer data, including the per-customer RAG corpus, will be stored on NZ-based servers in compliance with the NZ Privacy Act 2020. The platform will provide a clear, plain-English privacy policy explaining exactly what data is collected, how it is used, and how customers can access, correct, or delete it.

### 10.4 Fitment Data

The vessel and engine compatibility data will be sourced from a combination of manufacturer APIs, industry databases (e.g., ACES/PIES equivalents for marine), and manual curation. This data is the foundation of the "My Vessel" feature and must be maintained with rigorous accuracy.

---

## 11. Phased Rollout Roadmap

| Phase | Timeline | Key Deliverables |
|---|---|---|
| **Phase 1: Foundation** | Months 1–4 | Core e-commerce platform; product catalogue; "My Vessel" garage (basic); keyword search; checkout; account management |
| **Phase 2: Intelligence** | Months 5–8 | Vessel-scoped search and filtering; first 4 domain-specialist agents (Pumps, Electrical, Safety, Game Fishing); First Mate AI (basic — maintenance alerts, project lists) |
| **Phase 3: Content & Community** | Months 9–12 | Interactive OEM parts diagrams (outboard engines); "The Boat Ramp" content hub; community forum; service provider directory; NZ Regulatory Centre |
| **Phase 4: Deep Personalisation** | Months 13–18 | Full First Mate AI capability suite; all 12 domain-specialist agents; fishing trip planner; logbook; cost-of-ownership tracking |
| **Phase 5: Ecosystem** | Months 19–24 | Trade API; mobile app with offline parts lookup; service provider marketplace; third-party integrations (weather, tides, fishing reports) |

---

## 12. Conclusion: Why This Will Win

The NZ marine and fishing market is ready for a platform that treats its customers as the passionate, knowledgeable enthusiasts they are — not as anonymous shoppers browsing a catalogue. The three incumbent retailers have built their online presence on a conventional retail model that is increasingly inadequate for a customer base that expects personalisation, expertise, and genuine value from every digital interaction.

**Helm** will win by doing three things better than anyone else in New Zealand:

**Knowing your boat.** The "My Vessel" garage and vessel-scoped filtering will make every interaction more relevant and every purchase more confident. This is the foundation upon which everything else is built.

**Knowing your domain.** The suite of domain-specialist AI agents, each powered by a deep, curated RAG corpus, will provide a level of technical expertise that no human customer service team can match at scale. Whether a customer is troubleshooting a sanitation system or planning a game fishing trip, they will get the right answer, every time.

**Knowing you.** The First Mate personalised AI agent will transform the platform from a store into a partner. By building a rich, private understanding of each customer's vessel, projects, and preferences, it will provide proactive, predictive, and deeply personal assistance that creates a level of loyalty that no competitor can undercut with a price match.

This is not an incremental improvement on what Marine Deals, Burnsco, and Smart Marine offer. It is a fundamentally different kind of platform — and that difference is what will make it the first choice for every Kiwi boatie.

---

## Appendix A: Domain-Specialist Agent RAG Corpus Sources

| Agent | Primary RAG Sources |
|---|---|
| Pumps & Plumbing | Jabsco, Rule, Whale, Tru Design, Seaflo product manuals; AS/NZS 1546; ABYC H-31 |
| Galley | Dometic, Webasto, Force 10, Eno, Dickinson manuals; AS/NZS 5601.2; NZ gasfitting regs |
| Electronics | Garmin, Simrad, Raymarine, B&G, Standard Horizon manuals; Maritime NZ radio licensing; ITU regulations |
| Electrical & Solar | Victron, Mastervolt, CTEK, Enerdrive documentation; ABYC E-11; AS/NZS 3000 (Wiring Rules) |
| Rigging & Deck | Ronstan, Harken, Lewmar, Selden, Antal manuals; sailing technique guides; NZ Sailing Trust resources |
| Anchoring & Mooring | Maxwell, Lofrans, Muir, Rocna, Manson manuals; NZ anchoring regulations; seabed type guides |
| Safety & Compliance | Maritime NZ regulations; SOLAS; NZ Coast Guard resources; lifejacket service schedules; EPIRB registration |
| Game Fishing | IGFA rules; NZ Sport Fishing Council regulations; species-specific technique guides; local charter fleet reports |
| Soft Bait & Inshore | NZ inshore species guides; regional fishing reports; Fishy Business NZ; tackle manufacturer guides |
| Trailer & Towing | NZTA trailer regulations; Dunbier, Voyager, Mackay manuals; WOF requirements; towing capacity databases |
| Antifouling & Maintenance | Altex, International Paint, Jotun guides; NZ biosecurity requirements; engine manufacturer service manuals |
| Navigation & Regulations | Maritime NZ rules; NZ Coastal Pilot; LINZ chart updates; Maritime Transport Act 1994 |

---

## Appendix B: "First Mate" Agent — Conversation Flow Examples

**Example 1: Proactive Maintenance Alert**

> *First Mate:* "Hi [Name], just a heads-up — based on the engine hours you logged last month, your Yamaha F150 is due for its 100-hour service. I've put the correct Yamalube 10W-30 (4L), oil filter, fuel filter, and a new impeller into a temporary cart for you. The total is $187. The service manual section for this job is here. Want me to add these to your cart, or would you prefer to book a service with a Yamaha-certified mechanic? I can see [Local Mechanic Name] in [City] has great reviews and is available next week."

**Example 2: Troubleshooting**

> *Customer:* "My electric toilet keeps running after it's flushed."
>
> *First Mate:* "That's a common issue with the Jabsco Quiet Flush you have on your Riviera 43 — I can see you bought it in 2023. The most likely cause is a worn joker valve, which is a simple and cheap fix. Here's a 3-minute video showing exactly how to replace it on your model. The replacement valve is $18 and is in stock. Alternatively, it could be a faulty solenoid — if the joker valve fix doesn't work, here's the next diagnostic step. Want me to add the joker valve to your cart?"

**Example 3: Project Planning**

> *Customer:* "I want to add a solar setup to my boat."
>
> *First Mate:* "Great project for your Stabicraft 529 Frontier! Based on your boat size and typical usage, I'd recommend a 200W setup. Here's what you'll need: a 200W flexible solar panel ($320), a Victron SmartSolar 75/15 MPPT controller ($195), a 100Ah lithium battery ($890), a battery monitor ($85), and the wiring and fusing kit ($65). Total: approximately $1,555. I've created a project list with all these items. The installation is moderately complex — here's a guide. Would you like me to find a certified marine electrician in your area who can do the installation?"
