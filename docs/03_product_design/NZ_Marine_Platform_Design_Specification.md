# Product Design & Feature Specification

## Project: World-Class B2C Marine & Fishing E-Commerce Platform for New Zealand

**Author:** Manus AI | **Date:** February 2026

---

### 1. Executive Summary

This document outlines the product design and feature specification for a new, world-class B2C e-commerce platform for boat parts and fishing equipment, specifically tailored for the New Zealand market. The platform is designed to achieve a significant competitive advantage over existing NZ retailers — namely **Marine Deals, Burnsco, and Smart Marine** — by moving beyond transactional e-commerce and creating a deeply personalised, proactive, and knowledge-driven ecosystem for boat owners and fishing enthusiasts.

The core of this strategy is a **dual-agent AI architecture**. This consists of: 
1.  **Domain-Specialist AI Agents:** Experts in specific marine and fishing categories, powered by curated Retrieval-Augmented Generation (RAG) corpuses.
2.  **A Personalised "First Mate" AI Agent:** A dedicated AI companion for each customer, which builds a private RAG corpus based on the customer's vessel, projects, and behaviour to provide hyper-contextual advice and assistance.

This AI-driven approach, combined with best-in-class e-commerce features like interactive parts diagrams and a "My Vessel" garage concept, will create a platform that is not just a store, but an indispensable tool for every Kiwi boatie.

---

### 2. Competitive Landscape & Market Opportunity (New Zealand)

An audit of the three primary NZ competitors reveals a significant market opportunity. While all three are established retailers, their online offerings are largely conventional e-commerce stores focused on a broad range of outdoor products. They function as digital catalogues and lack the specialised, value-add features that define modern, best-in-class parts websites.

**Common Gaps Across All NZ Competitors:**

| Feature Gap | Description of Opportunity |
|---|---|
| **No Vessel Profile ("Garage")** | No competitor allows users to save their boat's details to filter the catalogue. This is the single biggest opportunity for personalisation and reducing customer friction. |
| **No AI-Powered Assistance** | The complete absence of AI represents a blue-ocean opportunity to leapfrog the competition with intelligent search, recommendations, and support. |
| **No Interactive Parts Diagrams** | Finding specific OEM parts is a major pain point. Providing interactive schematics would be a game-changing feature for the DIY and professional market. |
| **Lack of Deep Specialisation** | The competitors are generalists. A platform focused purely on marine and fishing can offer deeper expertise, a more curated product range, and more relevant content. |
| **No Community or Service Integration** | There is no central hub for Kiwi boaties to connect, share knowledge, or find qualified marine technicians. |

This analysis confirms that a platform built on deep specialisation, personalisation, and AI-driven expertise can capture a commanding market position.

---

### 3. Core Platform Features (The Foundation)

These features are the essential "table stakes" required to compete. The implementation must be flawless and user-centric.

- **Advanced Search:** Keyword, part number, and cross-reference search with fast, relevant results.
- **Intuitive Navigation:** A clean, logical hierarchy based on categories (e.g., Plumbing, Electrical, Rigging) and brands.
- **High-Quality Product Pages:** Multiple high-resolution images, detailed specifications, stock availability (per-store and online), and verified customer reviews.
- **Secure, Streamlined Checkout:** Multiple payment options (including AfterPay/Laybuy), guest checkout, and a simple, mobile-friendly process.
- **Comprehensive Account Management:** Order history, tracking, returns management, and saved addresses.
- **Mobile-First Responsive Design:** A seamless experience on all devices.
- **Click & Collect:** Integration with a physical store or pickup points.

---

### 4. Differentiating Features (The Competitive Moat)

These features will create a defensible competitive advantage.

#### 4.1. "My Vessel" (The Digital Garage)

This is the central hub for personalisation. Upon signing up, users are prompted to add their vessel(s).

- **Data Captured:** Make, model, year, length, HIN, registration number, primary use (e.g., inshore fishing, offshore cruising).
- **Engine & Systems:** Users can add specific details for their engine(s) (make, model, year, serial number, hours), electronics (chartplotter model, VHF model), batteries, plumbing systems, etc.
- **Automated Filtering:** Once a vessel is selected, the entire site automatically filters to show only compatible parts and accessories.

#### 4.2. Interactive OEM Parts Diagrams

In partnership with major engine and equipment manufacturers (e.g., Yamaha, Mercury, Simrad, Dometic), the platform will feature a library of interactive, exploded-view schematics.

- **Functionality:** Users can navigate to their specific engine or product model, view the diagram, click on any component, and be taken directly to the product page for that part. This eliminates guesswork and ensures accuracy.

#### 4.3. Content & Community Hub: "The Boat Ramp"

This integrated section transforms the site from a store into a resource.

- **Expert Guides & Video Content:** In-depth articles and video tutorials on installation, maintenance, and DIY projects, written by NZ marine experts.
- **NZ Fishing Reports & Local Knowledge:** A dedicated section with up-to-date fishing reports from around NZ, including user-submitted reports, local expert blogs, and integration with weather/tide data.
- **Community Forum:** A space for users to ask questions, share projects, and connect with fellow boaties.
- **Service Provider Directory:** A curated and rated directory of qualified marine technicians, electricians, mechanics, and boat builders across New Zealand.

#### 4.4. NZ Regulatory & Safety Centre

A dedicated resource to help Kiwi boat owners stay safe and compliant.

- **Content:** Plain-English guides to Maritime NZ rules, safety equipment requirements (e.g., lifejacket servicing, flare expiry), and regional council bylaws.
- **Integration:** This content will be linked directly from relevant product pages and proactively surfaced by the customer's AI agent.

---

### 5. AI Architecture: The Dual-Agent Model

The platform's intelligence is driven by two distinct but interconnected types of AI agents.

#### 5.1. Domain-Specialist AI Agents

These are a suite of expert agents, each focused on a specific category.

- **Examples:** The "Pump Pro," the "Galley Guru," the "Electronics Expert," the "Game Fishing Guide."
- **RAG Corpus:** Each agent is powered by a curated RAG corpus containing:
    - Product manuals and specifications
    - Installation guides
    - Manufacturer knowledge bases
    - Relevant NZ regulations and standards (e.g., AS/NZS 5601 for gasfitting)
    - Expert articles and forum posts
- **Function:** When a user asks a technical question ("*What's the best anchor for a 6m boat in the Marlborough Sounds?*" or "*My Jabsco toilet won't stop running*."), the query is routed to the appropriate specialist agent. This agent uses its RAG corpus to provide an accurate, detailed, and context-aware answer, far beyond the capabilities of a generic chatbot.

#### 5.2. The Personalised "First Mate" AI Agent

This is the core of the personalised experience, a dedicated AI companion for every signed-in customer.

- **Private RAG Corpus:** The First Mate AI builds and maintains a unique, private RAG corpus for its specific customer. This "customer memory" contains:
    - **Explicit Data:** All information from the "My Vessel" profile, project lists, fishing preferences, and wishlists.
    - **Implicit Data:** Purchase history, browsing history, and conversation logs with the agent.
- **Function:** The First Mate AI leverages this deep personal context to provide proactive, predictive, and hyper-relevant assistance. It acts as the orchestrator, querying the Domain-Specialist agents on the customer's behalf but adding the crucial layer of personal context.

---

### 6. "First Mate" AI Agent: Expanded Capabilities

The First Mate AI's role is to be the customer's indispensable digital partner. Beyond the core capabilities outlined in the initial design, its potential extends to:

| Capability | Description |
|---|---|
| **Proactive Project Management** | When a user adds a chartplotter to a "Winter Upgrade" project list, the agent automatically adds the correct transducer, wiring loom, and mounting bracket, along with a link to the installation manual and a list of local certified installers. |
| **Predictive Maintenance & Safety** | Based on engine hours and purchase history, the agent sends alerts for upcoming service intervals (oil, filters, impellers) and safety gear expiry dates (flares, EPIRB battery, lifejacket service). It can pre-populate a cart with the required items. |
| **Conversational Troubleshooting** | A user can describe a problem like, *"My bilge pump keeps cycling on and off."* The agent, knowing the user's boat and pump model, can guide them through a diagnostic process, suggesting common causes (leaky skin fitting, faulty float switch) and linking to relevant products or guides. |
| **Automated Logbook & Cost Tracking** | The agent can help the user maintain a digital logbook of trips, maintenance performed (automatically logging parts purchased), and catches. It can also track the total cost of ownership for the vessel. |
| **Intelligent Trip & Fishing Planner** | A user can say, *"I'm planning to go fishing in the Hauraki Gulf on Saturday."* The agent can check the marine forecast, consult recent fishing reports from the community hub, and suggest a plan: *"The forecast is for 10-knot southwesterlies. Reports suggest the snapper are in the worm beds east of Rangitoto. Based on your past purchases, I recommend using your Gulp! soft baits. Don't forget to pack your sea anchor."* |
| **Budgeting & Resale Value Advisor** | The agent can help users budget for large projects by breaking them down into stages. Over time, by tracking upgrades and maintenance, it could even provide a rough estimate of the vessel's resale value based on market data. |
| **Seamless Onboarding for New Vessels** | When a user buys a new boat, they can tell the agent the make and model. The agent can then proactively create a baseline profile, suggest a standard list of essential safety gear required for that size vessel in NZ, and recommend common first upgrades. |

This level of proactive, personalised assistance is what will create deep, lasting customer loyalty and make the platform an essential part of the boating experience in New Zealand.

---

### 7. Conclusion

By combining a solid foundation of e-commerce best practices with a visionary, AI-driven approach to personalisation and expertise, this platform is designed not just to compete with, but to fundamentally redefine the marine and fishing retail market in New Zealand. The investment in the "My Vessel" concept and the dual-agent AI architecture will create a powerful competitive moat, delivering a user experience that is simply not possible for the incumbent generalist retailers to replicate.
