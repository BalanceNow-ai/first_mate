"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from .env file or environment variables."""

    # Application
    app_env: str = "development"
    secret_key: str = "change-me-in-production"
    allowed_origins: str = "http://localhost:3000,http://localhost:8080"
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://helm:password@localhost:5432/helm_db"
    redis_url: str = "redis://localhost:6379/0"

    # Supabase Auth
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""

    # Laybuy
    laybuy_api_key: str = ""
    laybuy_api_secret: str = ""
    laybuy_sandbox: bool = True

    # Strapi CMS
    strapi_url: str = "http://localhost:1337"
    strapi_api_token: str = ""

    # Typesense
    typesense_host: str = "localhost"
    typesense_port: int = 8108
    typesense_api_key: str = ""
    typesense_search_only_key: str = ""

    # NZ Post
    nzpost_client_id: str = ""
    nzpost_client_secret: str = ""
    nzpost_account_number: str = ""

    # Aramex NZ
    aramex_api_key: str = ""
    aramex_account_number: str = ""

    # Mapbox
    mapbox_access_token: str = ""

    # OpenAI
    openai_api_key: str = ""

    # AWS S3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_bucket: str = "helm-marine-assets"
    aws_region: str = "ap-southeast-2"

    # Email (Resend)
    resend_api_key: str = ""
    resend_from_email: str = "noreply@helmmarine.co.nz"

    # Firebase
    firebase_server_key: str = ""
    firebase_project_id: str = ""

    # Analytics
    posthog_api_key: str = ""
    posthog_host: str = "https://app.posthog.com"

    # Error Tracking
    sentry_dsn: str = ""

    # Helm Dash Delivery
    warehouse_lat: float = -36.8406  # Westhaven Marina, Auckland
    warehouse_lng: float = 174.7530
    helm_dash_base_fee: float = 25.00
    helm_dash_per_nm_fee: float = 8.00
    helm_dash_speed_knots: float = 25.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
