# Helm Platform — Phase 4 Development Prompt

**Objective:** Implement the medium-priority recommendations from the Phase 3 code review, focusing on integrating live data from third-party services (Strapi, Mapbox) and enhancing the UI/UX of core features.

**Branch:** `feature/phase-4`

---

## Part 1 — Strapi Integration for Signature Experiences

**Goal:** Replace the hardcoded list of experiences on the Crew Loyalty dashboard with a dynamic list fetched from a Strapi CMS.

### 1.1. Backend (`/backend`)

1.  **New Endpoint:** Create a new endpoint `GET /api/v1/loyalty/experiences`.
    *   **File:** `routers/loyalty.py`
    *   **Task:** This endpoint should make an HTTP GET request to your Strapi instance (`STRAPI_URL` from `config.py`) to fetch all entries from a `signature-experiences` collection.
    *   It should handle potential errors from the Strapi API and return a cached/default list if the service is unavailable.
    *   Define a `SignatureExperience` Pydantic schema for the response.

2.  **Redemption Validation:**
    *   **File:** `routers/loyalty.py`
    *   **Task:** In the `redeem_points` endpoint, complete the `TODO`. When `redemption_type` is `experience`, it must now:
        1.  Fetch the specific experience from Strapi by its ID.
        2.  Validate that the user has enough points to redeem it.
        3.  Raise an exception if the experience ID is not found or points are insufficient.

### 1.2. Frontend (`/frontend`)

1.  **New Provider:** Create a new `experiencesProvider`.
    *   **File:** `features/loyalty/providers/loyalty_provider.dart`
    *   **Task:** This `FutureProvider` should call the new `/api/v1/loyalty/experiences` endpoint.

2.  **Update Dashboard:**
    *   **File:** `features/loyalty/screens/crew_dashboard_screen.dart`
    *   **Task:** Replace the hardcoded `_ExperienceCard` widgets with a `ListView.builder` that is populated by the `experiencesProvider`. The UI should gracefully handle loading and error states.

---

## Part 2 — Live Mapbox Integration for Helm Dash

**Goal:** Replace the placeholder map on the delivery tracking screen with a live, interactive Mapbox map.

### 2.1. Frontend (`/frontend`)

1.  **Add Dependency:** Add the `flutter_mapbox_gl` package to `pubspec.yaml`.

2.  **Integrate MapboxMap:**
    *   **File:** `features/helm_dash/screens/delivery_tracking_screen.dart`
    *   **Task:** Replace the `Container` with the placeholder map with a `MapboxMap` widget.
    *   **Configuration:**
        *   Use the `MAPBOX_ACCESS_TOKEN` from your environment configuration.
        *   Set the style to a nautical/marine theme (e.g., `MapboxStyles.NAVIGATION_NIGHT_DAY`).
        *   The camera should be centered between the warehouse and the delivery coordinates.

3.  **Add Live Markers:**
    *   **Task:** Use `MapboxMapController` to add symbols (markers) to the map:
        1.  A static marker for the warehouse location.
        2.  A static marker for the user's pin-dropped delivery location.
        3.  A live-updating marker for the delivery vessel's position, using the data from the `deliveryLiveLocationProvider` stream.

---

## Part 3 — UI/UX Enhancements

**Goal:** Implement the two low-priority UI enhancements from the Phase 3 review.

### 3.1. Multi-Image Product Gallery

1.  **Backend:**
    *   **File:** `models/product.py` & `schemas/product.py`
    *   **Task:** Change the `images` field from `JSONB`/`dict` to `ARRAY(String)` in the model and `list[str]` in the schema. This will store a simple list of image URLs.

2.  **Frontend:**
    *   **File:** `features/products/screens/product_detail_screen.dart`
    *   **Task:** Replace the single `Image.network` widget with a gallery view.
        *   Use a `PageView.builder` to allow horizontal swiping through the list of image URLs from the product's `images` field.
        *   Add a `PageIndicator` (dots) below the gallery to show the current image index.
        *   Wrap the gallery in a `GestureDetector` that, on tap, opens a full-screen view of the image using the `photo_view` package (add it to `pubspec.yaml`).

### 3.2. Markdown Rendering for AI Chat

1.  **Frontend:**
    *   **File:** `features/ai_chat/screens/chat_screen.dart`
    *   **Task:** In the `_MessageBubble` widget, replace the `Text` widget that displays the assistant's message with a `MarkdownBody` widget from the `flutter_markdown` package (add it to `pubspec.yaml`).
    *   **Styling:** Configure the `MarkdownStyleSheet` to match the app's theme (e.g., link colors, code block backgrounds).

---

## TDD Requirements & Workflow

*   Continue to follow a strict TDD process. All new backend logic must have `pytest` tests. All new frontend widgets and providers must have `flutter_test` tests.
*   Work on a `feature/phase-4` branch.
*   Once complete, merge to `main` and notify Manus for the Phase 4 code review.
