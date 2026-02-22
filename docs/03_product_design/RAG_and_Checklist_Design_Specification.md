# Helm Platform: AI Agent Architecture & Voyage Checklist System

**Prepared by Manus AI | February 2026**

---

## 1. AI Agent Architecture: Brand-Specific Agents vs. Domain-Specific Agents

### 1.1. The Question: Should we have a RAG agent for each boat brand?

This is a critical architectural decision. A brand-specific agent (e.g., a "Stabicraft Agent," a "Rayglass Agent") seems intuitive but presents significant scalability and user experience challenges. A deeper analysis reveals a more robust and effective approach.

### 1.2. The Recommendation: No, We Should Not Have Brand-Specific Agents.

Creating a separate, siloed RAG agent for each boat brand is inefficient and would lead to a fragmented user experience. The optimal architecture is a **hybrid model** that combines our existing **domain-expert agents** with the user's personalised **"First Mate" agent**.

| Architectural Approach | Why It's Flawed |
|---|---|
| **Brand-Specific Agents** | **Not Scalable:** Requires building and maintaining hundreds of individual agents. <br> **Creates Knowledge Silos:** A question about 12V wiring would get different, potentially conflicting answers from different brand agents. <br> **Confusing UX:** The user has to know which agent to talk to. They just want to talk to "the boat expert." |

### 1.3. The Correct Architecture: Brand-Specific *Data*, Not Agents

The power of the platform comes from layering different knowledge sources dynamically. The correct approach is to have **brand-specific data** that our **domain-expert agents** can access when needed, orchestrated by the user's personal "First Mate."

**The User Interaction Flow:**

1.  The user asks their personal **"First Mate"** agent a question: *"My 2022 Stabicraft 2250 is having trouble starting. What should I check?"*

2.  The **First Mate** agent already knows the user's vessel from the **Boat OEM Database**. It knows this boat was factory-fitted with a Yamaha F200XCA outboard.

3.  The First Mate agent queries the **"Engine & Propulsion Pro"** domain agent.

4.  The Engine & Propulsion Pro agent accesses its RAG corpus, which contains:
    *   General outboard troubleshooting guides.
    *   The specific **Yamaha F200XCA owner's manual**.
    *   The **Yamaha F200XCA service manual**.
    *   A database of common fault codes for that engine model.

5.  The Engine & Propulsion Pro agent synthesises this information and provides a specific, actionable answer back to the First Mate, which then presents it to the user: *"Okay, for your Yamaha F200, the most common starting issues are a fouled spark plug or a clogged fuel filter. Here is a link to the exact spark plugs you need, and here is a video showing how to change the primary fuel filter on your specific engine model. Would you like me to add both to your cart?"*

This architecture is **scalable, efficient, and provides a seamless user experience**. The user only ever talks to their First Mate, which intelligently draws on the deep knowledge of the various domain experts in the background.

---

## 2. The Voyage Checklist System

### 2.1. The Objective

To provide every Helm user with a set of clear, actionable, and authoritative checklists for the spare parts they should carry on board, tailored to their specific type of boating. This feature directly enhances safety, builds user trust, and drives the sale of high-margin spare parts.

### 2.2. The Three-Tiered Checklist Structure

The system is based on a three-tiered approach, reflecting the different risk profiles of different voyage types. Each tier builds upon the last.

*   **Tier 1: The "Grab & Go" Kit (Day Trips)**
    *   **Purpose:** The absolute minimum spares for any trip, even a short afternoon fish. Designed to handle the most common, high-probability failures that can be fixed with basic tools.
    *   **Format:** A printable checklist designed to fit in a dedicated, waterproof grab bag.

*   **Tier 2: The Coastal Cruising Kit (Weekend & Multi-Day Trips)**
    *   **Purpose:** Builds on the Grab & Go kit with spares for systems that see more use on longer trips. Assumes the vessel is operating within a few hours of a port.
    *   **Format:** An interactive checklist within the "My Vessel" garage, linked directly to the relevant products.

*   **Tier 3: The Offshore Passage Kit (Blue Water & Extended Voyages)**
    *   **Purpose:** A comprehensive kit for true self-sufficiency on long-distance passages where no outside help is available. Covers every critical system on the vessel.
    *   **Format:** A detailed, multi-page document with part numbers, recommended quantities, and links to service manuals.

### 2.3. The Checklist Content

The checklists are generated dynamically based on the user's specific vessel profile in their "My Vessel" garage. The system knows what engine, electronics, and plumbing systems are on board and tailors the checklist accordingly.

#### Tier 1: The "Grab & Go" Kit (Example for a 6m trailer boat)

| System | Spare Part | Quantity |
|---|---|---|
| **Engine (Outboard)** | Spare Propeller & Prop Nut/Split Pin | 1 |
| | Spare Engine Fuel Filter (primary) | 2 |
| | Spare Spark Plugs | 1 set |
| | Spare Kill Switch Lanyard | 1 |
| **Electrical** | Spare Navigation Light Bulbs (if not LED) | 1 set |
| | Assorted Fuses (5A, 10A, 15A) | 1 pack |
| **General** | Duct Tape | 1 roll |
| | Zip Ties (assorted sizes) | 1 pack |
| | Stainless Steel Hose Clamps (assorted sizes) | 1 pack |
| | Emergency Wooden Bungs (tapered) | 1 set |
| **Tools** | Shifting Spanner, Pliers, Screwdriver Set, Prop Spanner, Spark Plug Spanner |

#### Tier 2: The Coastal Cruising Kit (Adds to Tier 1)

| System | Spare Part | Quantity |
|---|---|---|
| **Engine (Outboard)** | Spare Water Pump Impeller & Gasket | 1 |
| | Spare Thermostat & Gasket | 1 |
| | Spare Alternator/Serpentine Belt | 1 |
| | Engine Oil (1L top-up) | 1 |
| **Plumbing** | Spare Bilge Pump (cartridge or complete) | 1 |
| | Spare Toilet Duckbill Valves / Joker Valves | 1 set |
| **Electrical** | Spare Battery Terminals | 1 set |
| | Small Spool of Marine-Grade Electrical Wire | 1 |
| | Butt Connectors & Crimper | 1 kit |
| **Tools** | Full Socket Set, Multimeter, Strap Wrench (for filters) |

#### Tier 3: The Offshore Passage Kit (Adds to Tiers 1 & 2)

| System | Spare Part | Quantity |
|---|---|---|
| **Engine (Outboard)** | Spare Fuel Pump (lift or high-pressure) | 1 |
| | Spare Ignition Coil | 1 |
| | Full Gasket Set | 1 |
| | Engine Oil & Filters for a full change | 1 set |
| **Plumbing** | Complete Spare Freshwater Pump | 1 |
| | Major Bilge Pump Rebuild Kit | 1 |
| | Assorted Hose & Fittings | 1 kit |
| **Electrical** | Spare VHF Antenna | 1 |
| | Spare GPS Antenna | 1 |
| | Spare Inverter/Charger (if fitted) | 1 |
| **Steering** | Spare Hydraulic Steering Fluid & Bleed Kit | 1 |
| **Sails (if applicable)** | Sail Repair Kit (needles, wax thread, patches) | 1 |
| | Spare Blocks, Shackles, and Cleats | Assorted |

### 2.4. User Experience & Integration

*   The checklists will be a prominent feature within the **"My Vessel" garage**.
*   Each checklist item will be a link that, when clicked, takes the user directly to the correct product page for their specific boat model.
*   Users can check off items they already have on board, and the system will maintain a "shopping list" of the remaining items.
*   The platform can send automated reminders, e.g., *"You're heading into summer, have you checked your offshore spares kit?"*
*   This feature provides immense value to the user, enhances their safety and preparedness, and directly drives sales of the most critical and highest-margin products on-hand inventory items.
