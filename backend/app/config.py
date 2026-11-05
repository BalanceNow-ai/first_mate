"""Application configuration loaded from environment variables.

Every external integration is configured explicitly. Local substitutes (local
payments, deterministic embeddings/LLM, fixture CMS, development auth) exist so the
whole application can be exercised offline, but they are *only* permitted when
``APP_ENV`` is ``development`` or ``test``. ``Settings.validate_runtime()`` is called
at API/worker start-up and refuses to start a production process that is
misconfigured or that has a local substitute enabled.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ENVS = {"development", "test"}
_DEFAULT_SECRET = "change-me-in-production"


class ConfigurationError(RuntimeError):
    """Raised when the runtime configuration is unsafe or incomplete."""


class Settings(BaseSettings):
    """Application settings (environment variables, optionally a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application -------------------------------------------------------------
    app_env: Literal["development", "test", "staging", "production"] = "development"
    secret_key: str = _DEFAULT_SECRET
    allowed_origins: str = "http://localhost:3000,http://localhost:8080"
    api_v1_prefix: str = "/api/v1"
    public_base_url: str = "http://localhost:8080"
    log_sql: bool = False

    # --- Database / cache --------------------------------------------------------
    database_url: str = "postgresql+asyncpg://helm:password@localhost:5432/helm_db"
    database_pool_size: int = 10
    database_max_overflow: int = 10
    redis_url: str = "redis://localhost:6379/0"

    # --- Authentication (Supabase) ----------------------------------------------
    # jwks   : asymmetric Supabase signing keys fetched from the project's JWKS URL.
    # hs256  : the project's *server-only* legacy JWT secret (never the anon key).
    # Both modes verify signature, algorithm, issuer, audience, expiry and subject.
    auth_mode: Literal["jwks", "hs256"] = "jwks"
    supabase_url: str = ""
    supabase_anon_key: str = ""  # public client key; NEVER used to verify tokens
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""  # server-only legacy signing secret (hs256 mode)
    supabase_jwt_issuer: str = ""  # default: {supabase_url}/auth/v1
    supabase_jwt_audience: str = "authenticated"
    supabase_jwks_url: str = ""  # default: {supabase_url}/auth/v1/.well-known/jwks.json
    supabase_require_email_confirmation: bool = True
    jwt_leeway_seconds: int = 30

    # --- Rate limiting -----------------------------------------------------------
    rate_limit_backend: Literal["redis", "memory", "disabled"] = "memory"
    rate_limit_auth_per_minute: int = 20
    rate_limit_ai_per_minute: int = 10
    rate_limit_ai_per_day: int = 200
    rate_limit_mutation_per_minute: int = 120
    rate_limit_webhook_per_minute: int = 600

    # --- Payments ----------------------------------------------------------------
    payment_provider: Literal["stripe", "local", "disabled"] = "disabled"
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    local_payment_webhook_secret: str = "whsec_local_development_only"
    reservation_minutes: int = 30
    min_charge_cents: int = 50  # Stripe NZD minimum charge

    # Afterpay / Laybuy: not implemented (see docs/08_delivery). Kept as explicit
    # disabled flags so the client can show the recorded reason.
    afterpay_enabled: bool = False
    laybuy_enabled: bool = False
    laybuy_api_key: str = ""
    laybuy_api_secret: str = ""
    laybuy_sandbox: bool = True

    # --- Shipping / delivery -----------------------------------------------------
    courier_rate_mode: Literal["rate_card", "nzpost", "disabled"] = "disabled"
    # JSON list of {"max_grams": int, "price_cents": int}; must be set explicitly in
    # production. Development falls back to DEV_RATE_CARD below.
    courier_rate_card: str = ""
    courier_service_name: str = "Standard courier"
    courier_estimated_days: int = 3
    courier_booking_enabled: bool = False  # live label creation/booking
    free_shipping_threshold_cents: int = 15000  # from the Phase-7 implementation
    quote_ttl_minutes: int = 20
    click_and_collect_enabled: bool = True
    click_and_collect_location: str = "Helm Marine, Westhaven Marina, Auckland"
    # Delivery types permitted for products flagged as dangerous goods.
    dangerous_goods_delivery_types: str = "click_and_collect"

    helm_dash_enabled: bool = False
    warehouse_lat: float = -36.8406  # Westhaven Marina, Auckland
    warehouse_lng: float = 174.7530
    helm_dash_base_fee_cents: int = 2500  # $25.00 (repository rate)
    helm_dash_per_nm_fee_cents: int = 800  # $8.00 / nm (repository rate)
    helm_dash_speed_knots: float = 25.0
    # Operator share of the delivery fee in basis points. Unset = payouts are recorded
    # as "rate_unconfigured" and no payout entitlement is created.
    helm_dash_operator_share_bps: int | None = None
    helm_dash_live_payouts_enabled: bool = False
    nzpost_client_id: str = ""
    nzpost_client_secret: str = ""
    nzpost_account_number: str = ""
    aramex_api_key: str = ""
    aramex_account_number: str = ""
    mapbox_access_token: str = ""  # public token, served to the client

    # --- AI / knowledge ----------------------------------------------------------
    ai_enabled: bool = False
    llm_provider: Literal["openai", "local_extractive", "disabled"] = "disabled"
    embedding_provider: Literal["openai", "local_hash", "disabled"] = "disabled"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    ai_max_message_chars: int = 2000
    ai_history_messages: int = 10
    ai_max_conversation_messages: int = 200
    ai_max_tool_iterations: int = 4
    ai_max_output_tokens: int = 900
    ai_request_timeout_seconds: float = 30.0
    rag_top_k: int = 5
    # Minimum cosine similarity for a chunk to count as evidence. Provider-specific:
    # the local hashing embedder produces lower absolute similarities.
    rag_min_similarity_openai: float = 0.35
    rag_min_similarity_local: float = 0.18
    fitment_min_confidence: float = 0.7

    # --- Content ------------------------------------------------------------------
    cms_provider: Literal["strapi", "local_fixture", "disabled"] = "disabled"
    strapi_url: str = ""
    strapi_api_token: str = ""
    cms_cache_seconds: int = 300

    # --- Search -------------------------------------------------------------------
    search_backend: Literal["typesense", "postgres"] = "postgres"
    typesense_host: str = "localhost"
    typesense_port: int = 8108
    typesense_protocol: str = "http"
    typesense_api_key: str = ""
    typesense_search_only_key: str = ""
    typesense_collection: str = "products"

    # --- Notifications -----------------------------------------------------------
    email_provider: Literal["resend", "smtp_sink", "log_sink", "disabled"] = "log_sink"
    resend_api_key: str = ""
    resend_from_email: str = "noreply@helmmarine.co.nz"
    smtp_sink_host: str = "localhost"
    smtp_sink_port: int = 1025
    push_provider: Literal["fcm", "log_sink", "disabled"] = "log_sink"
    firebase_project_id: str = ""
    firebase_service_account_json: str = ""
    notification_max_attempts: int = 6

    # --- Storage -----------------------------------------------------------------
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_bucket: str = "helm-marine-assets"
    aws_region: str = "ap-southeast-2"

    # --- Monitoring / analytics -------------------------------------------------
    posthog_api_key: str = ""
    posthog_host: str = "https://app.posthog.com"
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1
    worker_heartbeat_stale_seconds: int = 180

    # --- [commerce workstream] additional settings ------------------------------
    # Per-user request budgets for the money-moving endpoints.
    rate_limit_checkout_per_minute: int = 10
    rate_limit_payment_intent_per_minute: int = 30
    rate_limit_quote_per_minute: int = 30
    rate_limit_shipping_estimate_per_minute: int = 30  # public, per client address
    # Orders whose payment is processing / awaiting customer action are not expired
    # until this long after ``expires_at`` (the provider may still confirm them).
    payment_processing_grace_minutes: int = 30
    # Maximum orders released per run of the expiry task.
    reservation_release_batch_size: int = 100
    order_number_prefix: str = "HM"

    # --- [catalogue workstream] additional settings -----------------------------
    catalogue_default_page_size: int = 24
    catalogue_max_page_size: int = 100
    # Exact fitment evaluation runs over SQL-prefiltered candidates in batches.
    catalogue_fitment_batch_size: int = 500
    rate_limit_hin_per_minute: int = 30
    rate_limit_search_per_minute: int = 120
    typesense_timeout_seconds: float = 3.0
    typesense_import_batch_size: int = 200
    # Max Typesense hits evaluated for exact fitment when compatible_only=true.
    typesense_compatible_window: int = 250
    checklist_link_alternatives: int = 3


    # --- [knowledge-ai workstream] additional settings --------------------------
    knowledge_max_document_chars: int = 200_000  # per ingested document (API / CLI)
    knowledge_chunk_chars: int = 800  # target chunk size (heading-aware)
    knowledge_chunk_overlap_chars: int = 120
    knowledge_max_chunks_per_source: int = 400
    embedding_batch_size: int = 64  # texts per embeddings request
    rag_candidate_pool: int = 40  # nearest neighbours fetched before applicability filtering
    ai_tool_result_max_chars: int = 6000  # size bound of one tool result given to the model
    ai_max_products: int = 5  # product references returned per answer
    ai_max_specialists: int = 2  # keyword-routed specialist domains per turn


    # --- [rewards-delivery workstream] additional settings ----------------------
    crew_max_members: int = 10  # spec: crews of 2-10 (pending invites count too)
    crew_min_members_for_multiplier: int = 2
    crew_invite_days: int = 14
    points_per_dollar_redemption: int = 100  # 100 CP = $1 NZD
    profile_verification_bonus_points: int = 1000  # Boat DB spec §4.2
    helm_dash_location_max_age_seconds: int = 600  # reject reports older than 10 min
    helm_dash_location_future_skew_seconds: int = 30  # device clock tolerance
    resend_api_url: str = "https://api.resend.com"
    fcm_api_url: str = "https://fcm.googleapis.com"
    notification_batch_size: int = 50
    notification_backoff_base_seconds: int = 60
    notification_backoff_max_seconds: int = 21600
    notification_claim_lease_seconds: int = 300
    notification_http_timeout_seconds: float = 10.0
    service_reminder_renotify_days: int = 7



    # --- end of workstream settings ---------------------------------------------

    # ----------------------------------------------------------------------------
    @property
    def is_local(self) -> bool:
        return self.app_env in LOCAL_ENVS

    @property
    def jwt_issuer(self) -> str:
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer.rstrip("/")
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else ""

    @property
    def jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        return ""

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def dg_delivery_types(self) -> set[str]:
        return {t.strip() for t in self.dangerous_goods_delivery_types.split(",") if t.strip()}

    def courier_rate_table(self) -> list[dict[str, int]]:
        """Return the configured courier rate card (ascending by weight)."""
        if self.courier_rate_card:
            table = json.loads(self.courier_rate_card)
        elif self.is_local:
            table = DEV_RATE_CARD
        else:
            return []
        return sorted(
            ({"max_grams": int(r["max_grams"]), "price_cents": int(r["price_cents"])} for r in table),
            key=lambda r: r["max_grams"],
        )

    @property
    def payments_available(self) -> bool:
        if self.payment_provider == "stripe":
            return bool(self.stripe_secret_key and self.stripe_webhook_secret)
        return self.payment_provider == "local" and self.is_local

    @property
    def ai_available(self) -> bool:
        return (
            self.ai_enabled
            and self.llm_provider != "disabled"
            and self.embedding_provider != "disabled"
            and (self.llm_provider != "openai" or bool(self.openai_api_key))
            and (self.embedding_provider != "openai" or bool(self.openai_api_key))
        )

    @property
    def rag_min_similarity(self) -> float:
        if self.embedding_provider == "local_hash":
            return self.rag_min_similarity_local
        return self.rag_min_similarity_openai

    # ----------------------------------------------------------------------------
    def configuration_problems(self) -> list[str]:
        """Return a list of problems that make this configuration unsafe to run."""
        problems: list[str] = []

        # Authentication must always be verifiable.
        if self.auth_mode == "jwks":
            if not self.jwks_url:
                problems.append("AUTH_MODE=jwks requires SUPABASE_URL or SUPABASE_JWKS_URL")
        elif self.auth_mode == "hs256":
            if not self.supabase_jwt_secret:
                problems.append("AUTH_MODE=hs256 requires the server-only SUPABASE_JWT_SECRET")
            elif self.supabase_anon_key and self.supabase_jwt_secret == self.supabase_anon_key:
                problems.append("SUPABASE_JWT_SECRET must not be the public anon key")
            elif len(self.supabase_jwt_secret) < 32:
                problems.append("SUPABASE_JWT_SECRET is too short (min 32 characters)")
        if not self.jwt_issuer:
            problems.append("JWT issuer is not configured (SUPABASE_URL or SUPABASE_JWT_ISSUER)")
        if not self.supabase_jwt_audience:
            problems.append("SUPABASE_JWT_AUDIENCE must not be empty")

        if self.is_local:
            return problems

        # --- Non-local (staging / production) hard requirements ---------------------
        if self.secret_key == _DEFAULT_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be set to a random value of at least 32 characters")
        if any(o == "*" or "localhost" in o or "127.0.0.1" in o for o in self.origins):
            problems.append("ALLOWED_ORIGINS must list production origins only")
        if self.payment_provider == "local":
            problems.append("PAYMENT_PROVIDER=local is a test-only substitute")
        if self.payment_provider == "stripe" and not self.stripe_webhook_secret:
            problems.append("PAYMENT_PROVIDER=stripe requires STRIPE_WEBHOOK_SECRET")
        if self.payment_provider == "stripe" and not self.stripe_secret_key:
            problems.append("PAYMENT_PROVIDER=stripe requires STRIPE_SECRET_KEY")
        if self.llm_provider == "local_extractive" or self.embedding_provider == "local_hash":
            problems.append("Local AI substitutes are test-only; use openai or disable AI")
        if self.cms_provider == "local_fixture":
            problems.append("CMS_PROVIDER=local_fixture is a test-only substitute")
        if self.email_provider == "smtp_sink":
            problems.append("EMAIL_PROVIDER=smtp_sink is a local sink only")
        if self.rate_limit_backend != "redis":
            problems.append("RATE_LIMIT_BACKEND must be redis outside development/test")
        if self.courier_rate_mode == "rate_card" and not self.courier_rate_card:
            problems.append("COURIER_RATE_MODE=rate_card requires an explicit COURIER_RATE_CARD")
        if self.helm_dash_live_payouts_enabled:
            problems.append("Live Helm Dash payouts are not implemented; keep them disabled")
        if self.courier_booking_enabled:
            problems.append("Live courier booking is not implemented; keep it disabled")
        return problems

    def validate_runtime(self) -> None:
        """Raise ConfigurationError when the configuration must not be started."""
        problems = self.configuration_problems()
        if problems:
            raise ConfigurationError(
                "Refusing to start with unsafe configuration: " + "; ".join(problems)
            )


# Development-only courier rate card (values carried over from the Phase-7 code). It is
# never used outside development/test; production must configure COURIER_RATE_CARD.
DEV_RATE_CARD = [
    {"max_grams": 1000, "price_cents": 750},
    {"max_grams": 5000, "price_cents": 1290},
    {"max_grams": 15000, "price_cents": 1850},
    {"max_grams": 30000, "price_cents": 2990},
]


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
