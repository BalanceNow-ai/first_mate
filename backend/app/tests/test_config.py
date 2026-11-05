"""Production configuration must fail closed."""

import pytest

from app.config import ConfigurationError, Settings

GOOD_PROD = dict(
    app_env="production",
    secret_key="s" * 48,
    allowed_origins="https://app.helmmarine.co.nz",
    auth_mode="jwks",
    supabase_url="https://proj.supabase.co",
    rate_limit_backend="redis",
    payment_provider="stripe",
    stripe_secret_key="sk_live_x",
    stripe_webhook_secret="whsec_x",
    email_provider="resend",
    # Explicit so the test is independent of the test-process environment.
    llm_provider="disabled",
    embedding_provider="disabled",
    cms_provider="disabled",
    courier_rate_mode="disabled",
    courier_rate_card="",
)


def test_good_production_config_passes():
    Settings(**GOOD_PROD).validate_runtime()


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"secret_key": "change-me-in-production"}, "SECRET_KEY"),
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
    ],
)
def test_unsafe_production_config_refused(override, fragment):
    with pytest.raises(ConfigurationError) as exc:
        Settings(**{**GOOD_PROD, **override}).validate_runtime()
    assert fragment.lower() in str(exc.value).lower()


def test_production_has_no_default_rate_card():
    assert Settings(**GOOD_PROD).courier_rate_table() == []
    assert Settings(app_env="development").courier_rate_table()  # dev card exists
