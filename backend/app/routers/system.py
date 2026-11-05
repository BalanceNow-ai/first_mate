"""Liveness, readiness and the public client configuration."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, utcnow
from app.models.helm_dash import OperatingArea
from app.models.ops import WorkerHeartbeat

router = APIRouter(tags=["System"])

AFTERPAY_REASON = (
    "Afterpay is not offered: it requires an Afterpay-enabled Stripe account and a "
    "redirect-based confirmation flow that has not been implemented or validated."
)
LAYBUY_REASON = (
    "Laybuy is not offered: no merchant account or current API documentation has been "
    "validated for this integration."
)


@router.get("/health")
async def health() -> dict:
    """Liveness: the process is serving requests."""
    return {"status": "healthy", "service": "helm-api"}


@router.get("/ready")
async def ready(db: AsyncSession = Depends(get_db, scope="function")) -> JSONResponse:
    """Readiness: database reachable and migrated; reports worker heartbeat freshness."""
    settings = get_settings()
    checks: dict[str, dict] = {}
    ok = True
    try:
        await db.execute(text("SELECT 1"))
        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        checks["database"] = {"ok": True, "migration": version}
    except Exception:
        ok = False
        checks["database"] = {"ok": False}
    if settings.rate_limit_backend == "redis" or not settings.is_local:
        try:
            import redis.asyncio as redis

            client = redis.from_url(settings.redis_url, socket_timeout=1.0)
            await client.ping()
            await client.aclose()
            checks["redis"] = {"ok": True}
        except Exception:
            ok = False
            checks["redis"] = {"ok": False}
    try:
        beats = (await db.execute(select(WorkerHeartbeat))).scalars().all()
        stale_after = timedelta(seconds=settings.worker_heartbeat_stale_seconds)
        checks["workers"] = {
            b.name: {"last_seen_at": b.last_seen_at.isoformat(), "fresh": utcnow() - b.last_seen_at < stale_after}
            for b in beats
        }
    except Exception:
        checks["workers"] = {}
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "checks": checks})


@router.get("/api/v1/config/public")
async def public_config(db: AsyncSession = Depends(get_db, scope="function")) -> dict:
    """Non-secret configuration the client needs to decide which features to show."""
    s = get_settings()
    enabled_areas = (
        await db.execute(select(func.count()).select_from(OperatingArea).where(OperatingArea.enabled.is_(True)))
    ).scalar_one()
    courier_enabled = s.courier_rate_mode == "rate_card" and bool(s.courier_rate_table())
    helm_dash_enabled = s.helm_dash_enabled and enabled_areas > 0
    payment_methods = [
        {"id": "card", "enabled": s.payments_available, "reason": None if s.payments_available else "Payments are not configured"},
        {"id": "afterpay", "enabled": False, "reason": AFTERPAY_REASON},
        {"id": "laybuy", "enabled": False, "reason": LAYBUY_REASON},
    ]
    return {
        "environment": s.app_env,
        "currency": "NZD",
        "payments": {
            "provider": s.payment_provider if s.payments_available else "disabled",
            "stripe_publishable_key": s.stripe_publishable_key if s.payment_provider == "stripe" else None,
            "local_test_mode": s.payment_provider == "local" and s.is_local,
            "methods": payment_methods,
        },
        "delivery": {
            "courier": {
                "enabled": courier_enabled,
                "service_name": s.courier_service_name,
                "reason": None if courier_enabled else "Courier delivery is not configured",
                "development_rate_card": courier_enabled and s.is_local and not s.courier_rate_card,
            },
            "helm_dash": {
                "enabled": helm_dash_enabled,
                "reason": None if helm_dash_enabled else "Helm Dash is not operating",
            },
            "click_and_collect": {
                "enabled": s.click_and_collect_enabled,
                "location": s.click_and_collect_location,
            },
            "free_shipping_threshold_cents": s.free_shipping_threshold_cents,
            "dangerous_goods_delivery_types": sorted(s.dg_delivery_types),
        },
        "ai": {
            "enabled": s.ai_available,
            "mode": s.llm_provider if s.ai_available else "disabled",
            "local_substitute": s.ai_available and s.llm_provider == "local_extractive",
        },
        "content": {"provider": s.cms_provider, "local_fixture": s.cms_provider == "local_fixture"},
        "search": {"backend": s.search_backend},
        "mapbox_public_token": s.mapbox_access_token or None,
        "warehouse": {"lat": s.warehouse_lat, "lng": s.warehouse_lng},
    }
