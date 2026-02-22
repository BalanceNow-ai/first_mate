# Helm Platform — Phase 7 Development Prompt

**Objective:** Prepare the Helm platform for a production launch by focusing on performance, accessibility, monitoring, and deployment hardening.

---

## Part 1: Production Hardening (High Priority)

Your goal is to create a robust, secure, and scalable production deployment configuration.

### 1.1. Backend (`./backend`)

1.  **Create `Dockerfile.prod`:**
    *   Use a multi-stage build. The first stage (`builder`) installs all dependencies, including dev dependencies, to run tests.
    *   The final stage (`production`) should copy only the application code and production dependencies from the `builder` stage. **Do not install dev dependencies** (`pytest`, etc.) in the final image.
    *   Use `gunicorn` with `uvicorn` workers as the production server instead of `uvicorn --reload`. The `CMD` should be `gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:8000`.

2.  **Create `docker-compose.prod.yml`:**
    *   This file should mirror `docker-compose.yml` but be configured for production.
    *   The `api` service must use `Dockerfile.prod`.
    *   **Remove all `volumes` mounts for application code.** The code should be baked into the image.
    *   Instead of environment variables directly in the file, use an `env_file` directive to load configuration from a `.env.prod` file (which will not be committed to git).

### 1.2. Frontend (`./frontend`)

1.  **Add Production Build Scripts:**
    *   In `package.json` (or a new `scripts/` directory), add scripts for building production versions of the Flutter app:
        *   `build:android`: `flutter build appbundle --release`
        *   `build:ios`: `flutter build ipa --release`
        *   `build:web`: `flutter build web --release`

---

## Part 2: Performance & Accessibility (High Priority)

### 2.1. Performance Optimisation

1.  **Image Caching:** The `cached_network_image` package is already installed. Go through every `Image.network` widget in the app (product images, vessel photos, experience cards) and replace it with `CachedNetworkImage` to reduce network requests and improve perceived performance.

2.  **Provider Scoping:** Review all Riverpod providers. Add `.autoDispose` to any provider whose state is only needed by a single screen or a short-lived feature. This is crucial for preventing memory leaks as the app grows.

### 2.2. Accessibility (a11y)

1.  **Add `a11y` Linter Rules:** In `analysis_options.yaml`, add the following to your linter rules to enforce accessibility best practices:
    ```yaml
    include: package:flutter_lints/flutter.yaml

    linter:
      rules:
        # ... existing rules
        - secure_storage_check_ios_version
        - use_colored_box
        - use_decorated_box
        # Add these a11y rules
        - prefer_const_constructors
        - prefer_const_declarations
        - sized_box_for_whitespace
        - use_key_in_widget_constructors
    ```

2.  **Add Semantics:** Go through every screen and add a `Semantics` widget with a descriptive `label` for all `IconButton`s and other interactive elements that do not have a direct text label. This is critical for screen reader users.

---

## Part 3: Monitoring & Analytics (Medium Priority)

### 3.1. Error Monitoring (Sentry)

1.  **Backend:** In `app/main.py`, ensure the `sentry_dsn` is loaded from `settings` and that `sentry_sdk.init()` is called on application startup. Add a custom middleware that wraps requests in a `try...except` block and explicitly captures exceptions to Sentry.

2.  **Frontend:**
    *   Add the `sentry_flutter` package to `pubspec.yaml`.
    *   In `frontend/lib/main.dart`, initialize Sentry using the DSN from your environment configuration.
    *   Wrap the entire `runApp(const MyApp())` call in `SentryFlutter.init()` to automatically capture all unhandled exceptions.

### 3.2. Product Analytics (PostHog)

1.  **Frontend:**
    *   Add the `posthog_flutter` package to `pubspec.yaml`.
    *   In `frontend/lib/main.dart`, initialize PostHog.
    *   Implement event tracking for the following key user actions:
        *   `sign_up`: After successful registration.
        *   `login`: After successful login.
        *   `vessel_created`: In the `_handleSubmit` method of `vessel_form_screen.dart`.
        *   `order_completed`: In the `_ConfirmationStep` of `checkout_screen.dart`.
        *   `ai_conversation_started`: When a new chat is initiated.

---

## Workflow

1.  Create and switch to a new branch: `feature/phase-7`.
2.  Implement the changes as described above, following TDD principles.
3.  Commit your work regularly with clear messages.
4.  Merge the completed `feature/phase-7` branch into `main`.
5.  Notify Manus for the final Phase 7 code review.
