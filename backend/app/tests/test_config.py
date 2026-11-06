"""Production configuration must fail closed."""

import pytest

from app.config import ConfigurationError, Settings

GOOD_PROD = dict(
    app_env="production",
    secret_key="s" * 48,
    allowed_origins="https://app.helmmarine.co.nz",
    auth_mode="jwks",
    supabase_url="https://proj.supabase.co",
    supabase_service_role_key="service-role-test",
    rate_limit_backend="redis",
    payment_provider="stripe",
    stripe_secret_key="sk_live_x",
    stripe_webhook_secret="whsec_x",
    email_provider="resend",
    resend_api_key="re_test",
    push_provider="disabled",
    # Explicit so the test is independent of the test-process environment.
    llm_provider="disabled",
    embedding_provider="disabled",
    cms_provider="disabled",
    courier_rate_mode="disabled",
    courier_rate_card="",
    object_store_backend="s3",
    object_store_access_key="ak",
    object_store_secret_key="sk",
    upload_scanner="clamd",
    service_vision_provider="disabled",
)


def test_good_production_config_passes():
    Settings(**GOOD_PROD).validate_runtime()


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"secret_key": "change-me-in-production"}, "SECRET_KEY"),
        ({"object_store_backend": "local_fs"}, "OBJECT_STORE_BACKEND"),
        ({"object_store_secret_key": ""}, "OBJECT_STORE_ACCESS_KEY"),
        ({"upload_scanner": "local_signature"}, "UPLOAD_SCANNER"),
        ({"service_vision_provider": "local_fixture"}, "SERVICE_VISION_PROVIDER"),
        ({"service_vision_provider": "openai", "openai_api_key": ""}, "OPENAI_API_KEY"),
        ({"signed_url_seconds": 3600}, "SIGNED_URL_SECONDS"),
        ({"allowed_origins": "*"}, "ALLOWED_ORIGINS"),
        ({"payment_provider": "local"}, "test-only"),
        ({"stripe_webhook_secret": ""}, "STRIPE_WEBHOOK_SECRET"),
        ({"auth_mode": "hs256", "supabase_jwt_secret": ""}, "SUPABASE_JWT_SECRET"),
        ({"auth_mode": "hs256", "supabase_jwt_secret": "anon" * 10, "supabase_anon_key": "anon" * 10}, "anon key"),
        ({"supabase_url": ""}, "issuer"),
        ({"llm_provider": "local_extractive"}, "Local AI"),
        ({"embedding_provider": "local_hash"}, "Local AI"),
        ({"cms_provider": "local_fixture"}, "test-only"),
        ({"rate_limit_backend": "memory"}, "RATE_LIMIT_BACKEND"),
        ({"courier_rate_mode": "rate_card", "courier_rate_card": ""}, "COURIER_RATE_CARD"),
        ({"helm_dash_live_payouts_enabled": True}, "payouts"),
        ({"courier_booking_enabled": True}, "courier booking"),
        ({"email_provider": "log_sink"}, "local sink"),
        ({"supabase_service_role_key": ""}, "SUPABASE_SERVICE_ROLE_KEY"),
        ({"resend_api_key": ""}, "RESEND_API_KEY"),
        ({"push_provider": "log_sink"}, "local sink"),
        ({"push_provider": "fcm"}, "FIREBASE"),
        ({"cms_provider": "strapi"}, "STRAPI_URL"),
    ],
)
def test_unsafe_production_config_refused(override, fragment):
    with pytest.raises(ConfigurationError) as exc:
        Settings(**{**GOOD_PROD, **override}).validate_runtime()
    assert fragment.lower() in str(exc.value).lower()


def test_production_has_no_default_rate_card():
    assert Settings(**GOOD_PROD).courier_rate_table() == []
    assert Settings(app_env="development").courier_rate_table()  # dev card exists
