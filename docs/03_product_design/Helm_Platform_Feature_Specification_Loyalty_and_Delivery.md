# Helm Platform: Feature Specification
## Loyalty & Delivery Innovation

**Prepared by Manus AI | February 2026**

---

## Introduction

This document provides the detailed design specification for two innovative, high-impact features for the proposed Helm marine e-commerce platform: **"The Crew,"** a team-based rewards and experiences programme, and **"Helm Dash,"** an on-demand, Uber-style maritime delivery network. These features are designed to create a significant competitive moat, drive customer loyalty beyond simple price comparison, and solve a major logistical pain point for the New Zealand boating community.

---

## Part 1: "The Crew" — Team Rewards & Experiences Programme

### 1.1. Strategic Objective

The primary objective of "The Crew" is to transform the loyalty paradigm from a solitary, transactional relationship into a social, community-driven one. By rewarding collective spending and offering exclusive, money-can't-buy experiences, the programme aims to foster deep brand advocacy, increase customer lifetime value, and create a powerful network effect that is difficult for competitors to replicate.

### 1.2. Core Mechanics: The Crew Points (CP) System

The programme is built on a points-based currency, Crew Points (CP), which are earned on every purchase and can be pooled within a customer-defined "Crew."

*   **Base Earn Rate:** All customers earn a baseline of **1 Crew Point for every $1 NZD spent**.
*   **Crew Formation:** Customers can form or join a "Crew" of 2 to 10 members. All points earned by members are automatically deposited into a shared "Crew Wallet."
*   **The Accelerator Bonus:** The core of the programme is a tiered monthly spending bonus that applies to the entire Crew. The more a Crew spends collectively in a calendar month, the higher the points multiplier for every member.

| Collective Monthly Crew Spend (NZD) | Points Multiplier | Effective Earn Rate (CP per $1) |
| :--- | :--- | :--- |
| $0 - $499 | 1.0x | 1.0 |
| $500 - $999 | 1.25x | 1.25 |
| $1,000 - $1,999 | 1.5x | 1.5 |
| $2,000 - $4,999 | 2.0x | 2.0 |
| $5,000+ | **3.0x** | **3.0** |

This tiered structure incentivises both individual spending and, more importantly, the recruitment of active, high-spending members to a Crew to unlock the highest multipliers.

### 1.3. Redemption: Products & Signature Experiences

Crew Points have a dual redemption path, providing both tangible value and aspirational rewards.

*   **Product Discounts:** Points can be redeemed for discounts on any product on the platform at a fixed rate of **100 CP = $1 NZD**. This establishes a clear baseline value, ensuring the programme is always at least as rewarding as a standard 1% cashback offer.

*   **Signature Experiences:** The true differentiator of the programme is the ability to redeem points for a curated catalogue of exclusive, high-value marine experiences. These are not publicly available charter trips but unique, co-branded events designed to create lasting memories and deep brand affinity.

#### Example Signature Experiences Catalogue:

| Experience | Points Cost (CP) | Description |
| :--- | :--- | :--- |
| **Hauraki Gulf Kingfish Masterclass** | 150,000 | A full-day, private charter for 4 people with a top NZ fishing guide, targeting kingfish with advanced jigging and live-baiting techniques. Includes all gear, lunch, and a professional videographer. |
| **Marlborough Sounds Scallop & Sauvignon Trip** | 100,000 | A weekend trip for 2 people, staying at a luxury lodge in the Sounds. Includes a private water taxi to scallop beds, a cooking class with a local chef, and a winery tour. |
| **Bay of Islands Game Fishing Expedition** | 300,000 | A two-day trip for 4 people on a professional game fishing vessel during the peak of the marlin season. Includes all tackle, accommodation, and entry into a local fishing competition. |
| **Fiordland Discovery Voyage** | 500,000 | A 3-day, all-inclusive trip for 2 people on a private charter exploring Dusky and Doubtful Sounds, with a focus on wildlife photography and remote exploration. |

### 1.4. User Experience & Implementation

The programme will be integrated seamlessly into the main Helm platform.

*   **The Crew Dashboard:** A dedicated section within the user's account will serve as the central hub for the programme. Here, users can create or join a Crew, invite new members, view the shared Crew Wallet balance, and track collective spending.
*   **Gamification & Socialisation:** The dashboard will feature a prominent progress bar visualising the Crew's progress towards the next accelerator tier, creating a clear and motivating monthly goal. A simple, integrated chat function will allow Crew members to coordinate purchases and plan experience redemptions.
*   **Automated Point Allocation:** The system will be fully automated. At the end of each calendar month, it will calculate each Crew's total spend, apply the corresponding multiplier to each member's earned points for that month, and deposit the final CP amount into the shared Crew Wallet.

---

## Part 2: "Helm Dash" — On-Demand Maritime Delivery

### 2.1. Strategic Objective

Helm Dash is a premium, on-demand delivery service designed to solve the critical "last mile" problem for boaters in New Zealand's most popular marine environments. By providing rapid, reliable delivery of parts and supplies directly to a customer's vessel, Helm Dash creates a powerful, high-margin service that is completely unique in the NZ market and reinforces the platform's position as an indispensable partner to the boating community.

### 2.2. The Hybrid Operator Model

The service will be built on a flexible, scalable hybrid model that combines a company-owned flagship vessel with a network of trusted third-party partners.

*   **Flagship Vessel (Hauraki Gulf):** A dedicated, high-speed, company-owned vessel (e.g., a 7-9m RIB with a cabin and significant cargo capacity) will operate exclusively in the Hauraki Gulf. This vessel will be staffed by full-time, uniformed employees, serving as a highly visible brand ambassador and allowing for complete control over the customer experience in the initial launch market.

*   **Partner Network (Nationwide):** In other key regions (Bay of Islands, Tasman Bay, Marlborough Sounds), the platform will partner with existing, certified commercial water taxi and marine courier operators. These partners will be integrated into the Helm Dash platform via a dedicated app, allowing them to accept and fulfill delivery jobs on a contract basis. This model allows for rapid, capital-efficient expansion into new regions.

### 2.3. The Technology Platform

The service is powered by a three-part technology stack, analogous to the architecture of Uber or DoorDash.

1.  **Customer Interface (Integrated into main website/app):**
    *   During checkout, customers in eligible regions can select "Helm Dash" as a premium delivery option.
    *   A map interface allows the customer to drop a pin on their vessel's exact location, whether at a mooring, at anchor, or even underway.
    *   The system provides a real-time ETA and a dynamic delivery fee quote based on distance and urgency.
    *   Post-purchase, the customer can track the delivery vessel's progress in real-time on a map.

2.  **Partner Operator App ("Helm Dash Skipper"):**
    *   A dedicated mobile app for partner water taxi operators.
    *   Operators can set their availability (e.g., "Online" or "Offline").
    *   When a new delivery request is logged for their region, they receive a notification with the pickup location (the Helm warehouse or a local partner retailer), the delivery coordinates, and the offered payment.
    *   They can accept or decline the job with a single tap.
    *   The app provides turn-by-turn (or, rather, course-to-steer) navigation to the customer's vessel and facilitates in-app communication.

3.  **Central Dispatch & Logistics Dashboard (Admin Panel):**
    *   A web-based dashboard for the internal Helm logistics team.
    *   Provides a real-time, map-based overview of all active deliveries, vessel locations, and operator availability.
    *   Allows for manual assignment of jobs, dynamic pricing adjustments, and performance monitoring.
    *   Manages automated payments to partner operators.

### 2.4. Phased Rollout Plan

A phased rollout is recommended to manage risk and ensure a high-quality customer experience.

*   **Phase 1 (Months 1-6): Hauraki Gulf Launch.** Launch the service with the company-owned flagship vessel in the Hauraki Gulf. This provides a controlled environment to refine the technology, pricing model, and operational procedures.
*   **Phase 2 (Months 6-12): Marlborough Sounds & Bay of Islands Expansion.** Onboard the first 2-3 pre-vetted water taxi partners in both the Marlborough Sounds and the Bay of Islands. This will involve providing them with the Helm Dash Skipper app, training, and co-branded vessel livery.
*   **Phase 3 (Months 12-18): Tasman Bay & Nationwide Partner Onboarding.** Expand the partner network to Tasman Bay and actively recruit additional operators in all active regions to increase geographic coverage and reduce customer wait times.

### 2.5. Regulatory & Compliance

All operations will be conducted in strict compliance with New Zealand maritime law.

*   All company-owned vessels will be operated under the appropriate Maritime NZ certification (e.g., MOSS - Maritime Operator Safety System).
*   All partner operators must provide proof of their existing, valid commercial vessel certification and public liability insurance before being onboarded to the platform.
*   The platform will have clear, legally reviewed terms of service regarding the transport of dangerous goods (e.g., fuel, flares, batteries) to comply with all regulations and ensure the safety of all parties.
