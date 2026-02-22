## Personalised Customer AI Agent: Capabilities Design

This document outlines the capabilities of the personalised AI agent assigned to each signed-in customer. This agent is a core differentiator, transforming the e-commerce platform from a transactional store into a proactive, personalised boating and fishing partner.

### Core Concept: The Customer's Digital First Mate

Each customer receives their own dedicated AI agent, "First Mate AI." This agent's primary function is to build and maintain a unique, private Retrieval-Augmented Generation (RAG) corpus for that specific customer. This corpus acts as the agent's memory and knowledge base, enabling it to provide hyper-personalised advice and assistance.

### The Per-Customer RAG Corpus

The agent's effectiveness is directly proportional to the richness of its RAG corpus. This corpus is built from two sources:

| Data Source | Information Captured |
|---|---|
| **Explicit Data** | - **Vessel Profiles:** Detailed information from the "My Vessel" garage: make, model, year, length, engine details (make, model, serial, hours), HIN, onboard systems (electronics, plumbing, sanitation), battery setup, etc.<br>- **Project Lists:** User-created lists for current or future work (e.g., "Winter Maintenance 2026," "Galley Upgrade," "Trailer Refurbishment").<br>- **Fishing Preferences:** Preferred styles (game fishing, soft baiting, surfcasting), target species, and typical locations.<br>- **Skill Level:** Self-assessed expertise (e.g., "Beginner DIY," "Experienced Mechanic," "Professional Skipper").<br>- **Wishlists & Saved Items.** |
| **Implicit Data** | - **Purchase & Order History:** Every item ever bought.<br>- **Browsing & Interaction History:** Products viewed, articles read, videos watched, search queries used.<br>- **Agent Conversation Logs:** All questions asked and advice given.<br>- **Geographic Location:** Inferred from shipping address or browser data for local context. |

### Agent Capabilities

Based on its unique RAG corpus, the First Mate AI can perform a wide range of tasks that go far beyond a standard chatbot.

#### 1. Proactive & Predictive Assistance

The agent anticipates needs rather than just reacting to queries.

*   **Project-Based Recommendations:** When a user creates a "Galley Upgrade" project, the agent proactively suggests a curated list of compatible products: a new stove, the correct gas fittings and sealant, a compliant gas detector, and links to relevant installation guides and NZ-specific regulations (e.g., AS/NZS 5601).
*   **Predictive Maintenance Reminders:** Based on the vessel's engine model and usage hours (logged by the user or inferred from purchase history), the agent sends timely alerts: *"Hi [Customer Name], it's been about 100 hours since your last oil change for the Yanmar 3GM30. I've put the correct oil filter, 5L of Delo 400, and a replacement impeller into a temporary cart for you. Here's the service manual section for that job."*
*   **Safety & Compliance Management (NZ-Specific):** The agent tracks the expiry dates of safety equipment and alerts the user: *"Your flare kit is due to expire in 3 months. Here are the current Maritime NZ-compliant kits. Also, I see your lifejacket hasn't been serviced in two years; here's a link to find a local service agent."*

#### 2. Conversational Product Discovery & Troubleshooting

The agent acts as a true domain expert for the customer's specific context.

*   **Natural Language Troubleshooting:** A customer can state a problem in plain English: *"My bilge pump keeps running but no water is coming out."* The agent, knowing the customer's boat and likely setup, can initiate a diagnostic conversation: *"Okay, that sounds like an airlock or a blockage. Have you checked the intake for debris? Is the pump mounted lower than the outlet? Here's a quick video on how to prime your specific pump model."*
*   **Context-Aware Product Discovery:** Instead of searching for "12v bilge pump 500gph," the user can ask, *"What's a good bilge pump for my 5-meter Fyran runabout?"* The agent uses the vessel profile to recommend a correctly sized pump, and crucially, also suggests the necessary ancillary items: *"Based on your boat, the Rule-Mate 500 is a great option. You'll also need 2 meters of 19mm hose, two stainless steel hose clamps, and a new skin fitting. I've added them to a list for you."*

#### 3. Project & Task Management

The agent helps users plan and execute projects from start to finish.

*   **From Wishlist to Workflow:** The agent can convert a simple wishlist into a structured project plan. It can group items by installation sequence, estimate a budget, and create a checklist of tasks.
*   **Installation & Service Provider Integration:** For complex tasks, the agent can recommend qualified local service providers: *"Installing a new chartplotter requires specialist knowledge. Here are three certified marine electricians in the Auckland area with experience on Raymarine systems. Would you like me to request a quote on your behalf?"*

#### 4. Localised Knowledge & Community Integration

The agent connects the user to relevant local information and the wider community.

*   **Fishing Spot & Technique Advisor:** *"I'm heading to the Bay of Islands this weekend. What's been biting?"* The agent can access a RAG corpus of recent fishing reports, community forum posts, and local expert blogs to provide a summary: *"The snapper are schooling up around the Nine Pin. Soft baits in natural colours are working well. Here are a few top-rated soft baits that you've purchased before and a link to the latest fishing report from the local charter fleet."*
*   **Regulatory Guidance:** *"Can I anchor overnight in Urupukapuka Bay?"* The agent can provide up-to-date information on local anchoring rules, marine reserve boundaries, and biosecurity requirements (e.g., clean hull regulations for specific regions).

This personalised agent transforms the website from a catalogue into an indispensable tool, creating a powerful competitive moat built on data, trust, and genuine utility.
