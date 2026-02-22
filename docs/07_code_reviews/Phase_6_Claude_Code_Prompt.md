# Helm Platform — Phase 6 Development Prompt

**Objective:** Implement the final two user journey features required for an MVP launch: the User Profile screen and a simple Onboarding flow.

---

## Part 1: User Profile & Order History (High Priority)

**Location:** `frontend/lib/features/profile/`

### 1.1. Create New Routes

In `router.dart`, add a new top-level route `/profile` that maps to a new `UserProfileScreen`. This should be part of the main `ShellRoute`.

### 1.2. Build the `UserProfileScreen`

This screen will have three sections:

1.  **User Details:**
    - Display the user's full name and email from the `authStateProvider`.
    - Add an "Edit Profile" button that navigates to a new `EditProfileScreen`.
    - Add a "Log Out" button that calls the `signOut()` method on the `authStateProvider`.

2.  **Order History:**
    - Create a new `orderHistoryProvider` that fetches a list of the user's orders from a new `GET /api/v1/orders` backend endpoint.
    - Display the orders in a `ListView`, showing the order ID, date, total, and status.
    - Each item should be tappable, navigating to the existing `OrderDetailScreen` (`/orders/:orderId`).

3.  **Settings:**
    - Add a simple `SwitchListTile` for "Push Notifications" (state can be managed locally for now).

### 1.3. Build the `EditProfileScreen`

- A simple form with `TextFormField`s for "Full Name" and "Phone Number".
- Pre-populate the fields with the current user data.
- On save, call a new `updateProfile` method in the `api_service.dart` that makes a `PATCH` request to `/api/v1/users/me`.

### 1.4. Backend Endpoint

- In `orders.py`, create a new `GET /` endpoint that retrieves all orders for the current `user_id`, ordered by `created_at` descending.

---

## Part 2: Onboarding Flow (High Priority)

**Objective:** Guide new users to create their first vessel immediately after signing up to improve engagement and data capture.

### 2.1. Create `OnboardingScreen`

- **Location:** `frontend/lib/features/onboarding/screens/onboarding_screen.dart`
- This screen should be a simple, full-screen view with:
    - A welcome message (e.g., "Welcome to Helm!").
    - A brief explanation of why adding a vessel is important (e.g., "Add your boat to get personalised part recommendations and AI support.").
    - A large primary button: "Add My First Boat", which navigates to the existing `VesselFormScreen` (`/vessels/new`).
    - A secondary text button: "Skip for now", which navigates to the home screen (`/`).

### 2.2. Routing Logic

- In `signup_screen.dart`, after a successful sign-up, instead of navigating directly to `/`, navigate to a new `/onboarding` route.
- In `router.dart`, add the `/onboarding` route pointing to the `OnboardingScreen`.
- In the `VesselFormScreen`, after successfully creating a new vessel, check if the user came from the onboarding route. If so, navigate them to the home screen (`/`) instead of back to the vessel list.

---

## Part 3: Finalise Payment Integration (Medium Priority)

**Location:** `frontend/lib/features/checkout/screens/checkout_screen.dart`

- In the `_PaymentStep` widget, replace the placeholder `Container` for the Stripe card field with the actual `CardField` widget from the `flutter_stripe` package.
- Implement the `onConfirmOrder` logic to:
    1.  Call `Stripe.instance.confirmPayment` using the `client_secret` from the `checkoutProvider`.
    2.  On success, call the `confirmPayment()` method on the provider to move to the final step.
    3.  Handle any payment errors and display them to the user.

---

## TDD & Workflow

- **TDD is mandatory.** Every new screen must have a corresponding widget test file. Every new provider must have a unit test.
- Work on a `feature/phase-6` branch.
- Commit regularly with clear messages.
- When complete, merge to `main` and notify Manus for the final MVP code review.
