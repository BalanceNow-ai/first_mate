# Helm Platform — Phase 3 Development Prompt

**Objective:** Complete all backend `TODO` items from Phase 1 and build the three remaining core frontend features: Product Catalogue, Crew Loyalty, and Helm Dash.

**Branch:** `feature/phase-3`

---

## Part 1 — Phase 2 Frontend Remediation (Do First)

Before starting new features, please address the medium-priority recommendations from the Phase 2 code review.

1.  **Implement Full Supabase Auth Flow:**
    *   **File:** `frontend/lib/core/auth/auth_provider.dart`
    *   **Task:** In the `signIn` method, replace the placeholder logic with a proper call to `Supabase.instance.client.auth.signInWithPassword()`. On success, store the `session.accessToken` and `session.refreshToken` in `FlutterSecureStorage` using the `setTokens` method.

2.  **Implement Token Refresh Logic:**
    *   **File:** `frontend/lib/core/api/api_client.dart`
    *   **Task:** In the `AuthInterceptor`'s `onError` handler, complete the `TODO`. When a 401 error occurs, use the stored refresh token to call `Supabase.instance.client.auth.refreshSession()`. If successful, update the stored tokens and retry the original failed request using `handler.resolve()`.

---

## Part 2 — Phase 3 Backend Implementation (Complete `TODO`s)

Complete the remaining business logic in the backend.

1.  **Calculate Crew Points Multiplier:**
    *   **File:** `backend/app/routers/loyalty.py`
    *   **Task:** In the `get_current_multiplier` endpoint, replace the `TODO`. You need to:
        1.  Find the user's crew team.
        2.  Get all member IDs of that team.
        3.  Query the `Order` table to sum the `total_amount` for all members in the current calendar month.
        4.  Pass this calculated `monthly_spend` to the `_get_multiplier` function.

2.  **Implement Full LangChain Agent:**
    *   **File:** `backend/app/routers/ai.py`
    *   **Task:** In the `_run_first_mate_agent` function, replace the direct OpenAI call with a full LangChain agent implementation. The agent should:
        1.  Use a `ChatOpenAI` model.
        2.  Have access to a set of tools (e.g., `product_search_tool`, `vessel_data_tool`).
        3.  Use a ReAct-style agent executor to reason through problems and use tools to find answers.
        4.  The RAG (vector search) capability should be implemented as a tool that the agent can call.

---

## Part 3 — Phase 3 Frontend Implementation (New Features)

Build the following three features with full TDD (widget and unit tests).

### 1. Product Catalogue

*   **Product List Screen (`/products`):**
    *   **File:** `frontend/lib/features/products/screens/product_list_screen.dart`
    *   **Task:** Add a filter bar below the search bar that allows filtering by:
        *   **Category:** (Dropdown populated from a new `/api/v1/products/categories` endpoint).
        *   **Brand:** (Dropdown populated from a new `/api/v1/products/brands` endpoint).
        *   **On Sale:** (Toggle switch).
        *   **Vessel Compatible:** (Toggle switch, only visible if the user has a primary vessel set). This should add a `vessel_id` query parameter to the API call.
    *   Update the `productFilterProvider` to include these new filter options.

*   **Product Detail Screen (`/products/:productId`):**
    *   **File:** `frontend/lib/features/products/screens/product_detail_screen.dart`
    *   **Task:** Create a detailed view showing:
        *   A scrollable image gallery.
        *   Product name, brand, price, and stock status.
        *   A detailed HTML description section.
        *   An "Add to Cart" button.
        *   A section for "Compatible with your [Vessel Name]" if applicable.

### 2. Crew Loyalty Dashboard

*   **New Screen:** `/crew` (add to bottom navigation).
*   **Files:** `frontend/lib/features/loyalty/screens/crew_dashboard_screen.dart` and associated providers.
*   **Task:** Create a dashboard that displays:
    *   The user's current Crew Points balance (`/api/v1/loyalty/points`).
    *   The current points multiplier, monthly spend, and progress to the next tier (`/api/v1/loyalty/multiplier`).
    *   A list of the user's crew teams and their members (`/api/v1/loyalty/teams`).
    *   A scrollable list of redeemable "Signature Experiences" (fetched from Strapi or a new backend endpoint).

### 3. Helm Dash Delivery Tracking

*   **New Screen:** `/dash/:deliveryId`
*   **Files:** `frontend/lib/features/helm_dash/screens/delivery_tracking_screen.dart` and associated providers.
*   **Task:** Create a delivery tracking screen that:
    *   Fetches the delivery status from `/api/v1/helm-dash/deliveries/:deliveryId`.
    *   Displays a Mapbox view showing the delivery route from the warehouse to the vessel's pin-dropped location.
    *   Shows the live location of the delivery vessel (you can simulate this for now).
    *   Displays the current status (e.g., "En Route", "Delivered") and ETA.

---

## TDD Requirements

*   **Backend:** Every new endpoint and logic change must have corresponding `pytest` tests.
*   **Frontend:** Every new screen must have `flutter_test` widget tests covering its different states (loading, data, error). Every new Riverpod provider must have unit tests.

## Workflow

1.  Create and switch to a `feature/phase-3` branch.
2.  Implement the changes as described above, committing regularly.
3.  Once complete, merge the feature branch back into `main`.
4.  Notify Manus for the Phase 3 code review.
