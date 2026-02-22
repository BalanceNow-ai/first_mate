
# Helm Platform — Phase 2 Development Prompt

**Objective:** Remediate all Phase 1 backend issues and implement the full Phase 2 Flutter frontend application. All work should be committed directly to the `main` branch of the `BalanceNow-ai/first_mate` repository.

---

## Part 1: Phase 1 Backend Remediation

Before starting any frontend work, address the following high-priority issues in the existing backend code, as identified in the Phase 1 Code Review.

### 1.1. Harden Authentication Fallback

- **File:** `backend/app/middleware/auth.py`
- **Task:** Modify the `get_current_user_id` function.
    1.  Add a check at the beginning of the function: if `settings.app_env == "production"` and `not settings.supabase_anon_key`, raise a `RuntimeError` to prevent the application from starting with an insecure configuration.
    2.  Inside the `else` block for the development fallback, add a `logging.warning` call to print a prominent message to the console on startup, e.g., `"WARNING: Authentication is in insecure development mode. JWTs are not being cryptographically verified."`

### 1.2. Move Hardcoded Configuration

- **File:** `backend/app/routers/helm_dash.py`
- **Task:**
    1.  Remove the hardcoded `WAREHOUSE_LAT`, `WAREHOUSE_LNG`, `BASE_DELIVERY_FEE`, `PER_NM_FEE`, and `DELIVERY_SPEED_KNOTS` constants.
    2.  Add these variables to the `Settings` class in `backend/app/config.py` with appropriate default values.
    3.  Update the `helm_dash.py` router to import `get_settings` and use `settings.warehouse_lat`, etc.

### 1.3. Add Missing Test Coverage

- **Task:** Add new test files and functions to cover the following scenarios:
    1.  **`backend/app/tests/test_auth.py`**: Create a new test file. Add a test to ensure a user cannot access resources owned by another user (e.g., try to `GET` a vessel created by `test_user` while authenticated as a different user).
    2.  **`backend/app/tests/test_payments.py`**: Add a test for the Stripe webhook signature verification. You will need to mock the `stripe.Webhook.construct_event` call and assert that it is called correctly when a signature header is present.

---

## Part 2: Phase 2 Frontend Implementation (Flutter)

This is the primary focus of Phase 2. Create a new `frontend/` directory at the root of the repository and initialise a new Flutter project within it.

### 2.1. Project Setup & Architecture

- **Framework:** Flutter 3.x
- **State Management:** Riverpod
- **Routing:** GoRouter
- **HTTP Client:** Dio
- **Directory Structure:** Follow a standard feature-first structure:
    ```
    frontend/
    ├── lib/
    │   ├── main.dart
    │   ├── app.dart
    │   ├── core/           # Shared services, models, widgets
    │   │   ├── api/        # Dio client, API service classes
    │   │   ├── auth/       # Auth repository, Supabase client
    │   │   └── models/     # Data models (User, Vessel, etc.)
    │   └── features/       # Feature-based screens and providers
    │       ├── auth/
    │       ├── home/
    │       ├── vessels/
    │       ├── products/
    │       └── ai_chat/
    └── test/
    ```

### 2.2. Core Feature Implementation

Implement the following screens and features, ensuring they connect to the live backend API running via `docker-compose up`.

1.  **Authentication (`/features/auth`)**
    - Implement the Login and Sign Up screens using the Supabase Flutter SDK.
    - Support email/password and Google social login.
    - On successful login, securely store the JWT and refresh token. The Dio client should automatically attach the JWT to all subsequent API requests.

2.  **Home Screen (`/features/home`)**
    - This is the main dashboard after login.
    - Display a summary of the user's primary vessel (if any).
    - Show a list of recent AI conversations.
    - Include a prominent search bar.

3.  **My Vessel Garage (`/features/vessels`)**
    - Implement the full CRUD functionality for vessels, connecting to the `/api/v1/vessels` endpoints.
    - Create a `VesselListScreen` to display all of the user's vessels.
    - Create a `VesselDetailScreen` to show the full details of a single vessel.
    - Create a `VesselForm` widget for creating and editing vessels.

4.  **First Mate AI Chat (`/features/ai_chat`)**
    - Implement a chat interface that connects to the `/api/v1/ai/chat` endpoint.
    - The UI should display the conversation history.
    - When initiating a chat from a vessel's detail page, the `vessel_id` should be passed to the API.

### 2.3. TDD Approach

For every feature, follow a Test-Driven Development approach:

1.  **Write Widget Tests:** For each screen, write tests that verify the UI renders correctly and that user interactions (button presses, form inputs) trigger the expected state changes.
2.  **Write Unit/Integration Tests:** For each Riverpod provider and repository, write tests that mock the API service and verify that the correct data is fetched and state is managed.

---

## 3. Development Workflow

1.  Create a new branch `feature/phase-2` from `main`.
2.  Complete all **Part 1** backend remediation tasks and commit them to this branch.
3.  Complete all **Part 2** frontend implementation tasks, committing regularly to this branch.
4.  Ensure all new code includes corresponding tests.
5.  When the entire prompt is complete, merge the `feature/phase-2` branch back into `main`.
6.  **Do not create a pull request.** Commit directly to `main`.
7.  After the final commit, notify Manus for the Phase 2 code review.
