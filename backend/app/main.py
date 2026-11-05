"""Helm Marine Platform — FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.errors import install_error_handlers
from app.routers import (
    admin,
    ai,
    auth,
    cart,
    checklists,
    content,
    dispatch,
    equipment,
    helm_dash,
    knowledge,
    loyalty,
    notifications,
    orders,
    payments,
    products,
    search,
    shipping,
    system,
    users,
    vessels,
)

logger = logging.getLogger("helm")
API_VERSION = "1.0.0"


def _init_sentry(settings) -> None:
    if not settings.sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        environment=settings.app_env,
        release=f"helm-api@{API_VERSION}",
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_runtime()  # refuse to start an unsafe configuration
    _init_sentry(settings)
    logger.info("Helm API starting (env=%s)", settings.app_env)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Helm Marine Platform API",
        description=(
            "Vessel-aware marine commerce: My Vessel garage, verified fitment, the First Mate "
            "assistant, voyage checklists, Crew Rewards and Helm Dash delivery."
        ),
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    prefix = settings.api_v1_prefix
    for module in (
        auth, users, vessels, equipment, products, search, cart, orders, payments, shipping,
        ai, knowledge, checklists, loyalty, helm_dash, dispatch, content, notifications, admin,
    ):
        app.include_router(module.router, prefix=prefix)
    app.include_router(system.router)
    return app


app = create_app()
