# Loyalty & Delivery Innovation: Feature Specification

## Part 1: The Crew — Team Rewards & Experiences Programme

### 1. Core Concept: From Cashback to Community

The proposed loyalty programme, **"The Crew,"** is designed to move beyond simple transactional cashback and foster a sense of community and shared experience. It replaces a generic, individual cashback offer with a points-based system that encourages group participation and unlocks unique, money-can't-buy marine experiences.

### 2. Earning Points: The "Crew Points" (CP) System

*   **Base Earn Rate:** Every customer earns **1 Crew Point (CP) for every $1 NZD spent** on the platform.
*   **Individual & Team Points:** Points are earned individually but can be pooled into a "Crew Wallet." A Crew can be formed by 2 to 10 customers.
*   **The Accelerator Bonus:** This is the core mechanic. The more a Crew spends collectively in a calendar month, the higher the points multiplier for *all members of that Crew* for that month.

| Collective Monthly Crew Spend (NZD) | Points Multiplier | Effective Earn Rate (CP per $1) |
| :--- | :--- | :--- |
| $0 - $499 | 1.0x | 1.0 |
| $500 - $999 | 1.25x | 1.25 |
| $1,000 - $1,999 | 1.5x | 1.5 |
| $2,000 - $4,999 | 2.0x | 2.0 |
| $5,000+ | **3.0x** | **3.0** |

**Example:** A Crew of 4 people each spends $300 in a month. Their collective spend is $1,200. This unlocks the 1.5x multiplier. Each member will have their base 300 points multiplied by 1.5, earning 450 CP for the month, which are deposited into the shared Crew Wallet.

### 3. Redeeming Points: Products & Experiences

Crew Points can be redeemed in two ways:

*   **Product Discounts:** Points can be used to pay for products at a rate of **100 CP = $1 NZD**. This provides a baseline value and ensures the system is always at least as good as a 1% cashback offer.
*   **"Signature Experiences":** This is the primary value proposition. Points can be redeemed for a curated catalogue of exclusive marine experiences. These are not just standard charter trips; they are unique, high-value events organised by the platform.

### 4. The Signature Experiences Catalogue (Examples)

| Experience | Points Cost (CP) | Description |
| :--- | :--- | :--- |
| **Hauraki Gulf Kingfish Masterclass** | 150,000 | A full-day, private charter for 4 people with a top NZ fishing guide, targeting kingfish with advanced jigging and live-baiting techniques. Includes all gear, lunch, and a professional videographer. |
| **Marlborough Sounds Scallop & Sauvignon Trip** | 100,000 | A weekend trip for 2 people, staying at a luxury lodge in the Sounds. Includes a private water taxi to scallop beds, a cooking class with a local chef, and a winery tour. |
| **Bay of Islands Game Fishing Expedition** | 300,000 | A two-day trip for 4 people on a professional game fishing vessel during the peak of the marlin season. Includes all tackle, accommodation, and entry into a local fishing competition. |
| **Fiordland Discovery Voyage** | 500,000 | A 3-day, all-inclusive trip for 2 people on a private charter exploring Dusky and Doubtful Sounds, with a focus on wildlife photography and remote exploration. |

### 5. Implementation & UX

*   **The Crew Dashboard:** A dedicated section in the user account where customers can create or join a Crew, view collective spend, track progress towards the next multiplier tier, and see the shared Crew Points balance.
*   **Gamification:** The dashboard will feature a progress bar showing the Crew's monthly spend and the distance to the next accelerator bonus, creating a clear, motivating target.
*   **Social Features:** The Crew dashboard will include a simple chat function for members to coordinate purchases and plan experience redemptions.
*   **Automated Points Allocation:** At the end of each calendar month, the system calculates the collective spend, applies the correct multiplier, and distributes the Crew Points to the shared wallet.

## Part 2: Helm Dash — On-Demand Maritime Delivery

### 1. Core Concept: Uber for the Waterways

**"Helm Dash"** is a premium, on-demand delivery service designed to solve the last-mile problem for boaters in New Zealand's most popular marine environments. It provides rapid delivery of parts, supplies, and even food and beverages directly to a customer's vessel, whether at a mooring, at anchor, or even underway.

### 2. The Hybrid Operator Model

The service will operate on a hybrid model, combining a company-owned flagship vessel with a network of third-party partners.

*   **Flagship Vessel (Hauraki Gulf):** A dedicated, high-speed, company-owned vessel (e.g., a 7-9m RIB with a cabin and significant cargo capacity) will operate exclusively in the Hauraki Gulf. This vessel will be staffed by full-time employees and will serve as the primary brand ambassador for the service.
*   **Partner Network (Nationwide):** In other key regions (Bay of Islands, Tasman Bay, Marlborough Sounds), the platform will partner with existing, certified commercial water taxi and marine courier operators. These partners will be integrated into the Helm Dash platform, accepting and fulfilling delivery jobs on a contract basis.

### 3. The Technology Platform

The service is powered by a three-part technology stack, analogous to Uber Eats:

1.  **Customer Interface (Integrated into main website/app):**
    *   When checking out, customers can select "Helm Dash" as a delivery option.
    *   They can drop a pin on a marine chart to specify their vessel's exact location.
    *   The system provides a real-time ETA and delivery fee quote.
    *   Customers can track the delivery vessel's progress in real-time on a map.

2.  **Partner Operator App ("Helm Dash Skipper"):**
    *   A dedicated mobile app for partner water taxi operators.
    *   Operators can set their availability (e.g., "Online" or "Offline").
    *   When a new delivery request comes in for their region, they receive a notification with the pickup location (our warehouse or a local partner retailer), the delivery coordinates, and the offered payment.
    *   They can accept or decline the job with a single tap.
    *   The app provides navigation to the customer's vessel and facilitates communication (e.g., "Arriving in 5 minutes").

3.  **Central Dispatch & Logistics Dashboard (Admin Panel):**
    *   A web-based dashboard for our internal logistics team.
    *   Provides a real-time overview of all active deliveries, vessel locations, and operator availability.
    *   Allows for manual assignment of jobs if necessary.
    *   Manages payments to partner operators.

### 4. Phased Rollout Plan

*   **Phase 1 (Months 1-6): Hauraki Gulf Launch.** Launch the service with the company-owned flagship vessel in the Hauraki Gulf. This allows for a controlled rollout to refine the technology, pricing, and operational procedures.
*   **Phase 2 (Months 6-12): Marlborough Sounds & Bay of Islands Expansion.** Onboard the first 2-3 water taxi partners in both the Marlborough Sounds and the Bay of Islands. This will involve providing them with the Helm Dash Skipper app and training.
*   **Phase 3 (Months 12-18): Tasman Bay & Nationwide Partner Onboarding.** Expand the partner network to Tasman Bay and actively recruit additional operators in all active regions to increase coverage and reduce delivery times.

### 5. Regulatory & Compliance

*   All company-owned vessels will be operated under the appropriate Maritime NZ certification (e.g., MOSS - Maritime Operator Safety System).
*   All partner operators must provide proof of their existing, valid commercial vessel certification and insurance.
*   The platform will have clear terms of service regarding the transport of dangerous goods (e.g., fuel, flares) to comply with all maritime regulations.
