# Helm Platform — Phase 5 Development Prompt

**Objective:** Implement the two high-priority features from the Phase 4 review: the full multi-step checkout flow and the tiered voyage checklists.

**Branch:** `feature/phase-5`

---

## Part 1 — Voyage Checklists (Backend + Frontend)

This is the first high-priority feature. It involves creating the backend logic and frontend UI for the tiered voyage checklists.

### 1.1. Backend (`checklists.py`)

- **Enhance `generate_checklists`:** The current implementation uses a static list of item names. This needs to be upgraded to perform a product search for each item to find a matching `product_id`.
    - For each item in `GRAB_AND_GO_ITEMS`, `COASTAL_CRUISING_ITEMS`, and `OFFSHORE_PASSAGE_ITEMS`, use a simple keyword search against the `Product` table (e.g., `ILIKE '%{item_name}%'`).
    - If a single, unambiguous match is found, link its `product_id` in the created `ChecklistItem`.
    - If multiple matches or no matches are found, leave `product_id` as `null`. The user can link it manually in the UI later.

### 1.2. Frontend (New Feature)

- **Create `feature/checklists` directory.**
- **Create `VesselChecklistsScreen` (`/vessels/:vesselId/checklists`):
    - This screen should be accessible from a new "Checklists" button on the `VesselDetailScreen`.
    - It should display three expandable sections: "Grab & Go Kit", "Coastal Cruising Kit", and "Offshore Passage Kit".
    - If checklists haven't been generated for the vessel, it should show a single "Generate Checklists" button that calls the `POST /api/v1/checklists/vessel/{vessel_id}/generate` endpoint.
- **Checklist Item Widget:**
    - Each item in the list should have a checkbox to toggle its `is_checked` state (calling `PATCH /api/v1/checklists/items/{item_id}/toggle`).
    - If `product_id` is not null, the item name should be a tappable link that navigates to the `ProductDetailScreen`.
    - If `product_id` is null, show a "Link Product" button that opens a simple search dialog to find and link a product.
- **"Add Missing to Cart" Button:**
    - At the top of the screen, include a floating action button that, when pressed, adds all *unchecked* items that have a linked `product_id` to the user's cart.

---

## Part 2 — Multi-Step Checkout Flow (Frontend)

This is the second high-priority feature. It involves building the full multi-step checkout process.

### 2.1. Create `feature/checkout` directory.

### 2.2. Create `CheckoutScreen` (New Screen, `/checkout`)

This screen should be a `PageView` with 3 steps:

**Step 1: Shipping**
- Display a form for the user's shipping address.
- Allow selection between "Standard Shipping" and "Helm Dash" delivery.
- If "Helm Dash" is selected, show a map for the user to drop a pin for their delivery location.
- A "Continue to Payment" button validates the form and moves to the next page.

**Step 2: Payment**
- Display payment method options: Credit Card (Stripe), Afterpay, and Laybuy.
- Use the official Flutter packages for Stripe (`flutter_stripe`) to display the card input element.
- On "Confirm Order", create the order via `POST /api/v1/orders`, then use the returned `client_secret` from `POST /api/v1/payments/{order_id}/create-intent` to confirm the payment with the Stripe SDK.

**Step 3: Confirmation**
- Display a success message with the order number and a summary of the order details.
- A "Track Order" button should navigate to the `OrderDetailScreen` (to be created).

### 2.3. Create `OrderDetailScreen` (New Screen, `/orders/:orderId`)

- A simple screen that fetches and displays the full details of a completed order, including items, totals, and shipping status.

---

## 3. TDD & Workflow

- **TDD is mandatory.** Every new widget must have a corresponding widget test, and every new provider must have a unit test.
- Work on the `feature/phase-5` branch.
- Commit regularly with clear, descriptive messages.
- When the entire prompt is complete, merge to `main` and notify Manus for the Phase 5 code review.
