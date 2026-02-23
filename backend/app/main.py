"""Helm Marine Platform — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import (
    ai,
    auth,
    cart,
    checklists,
    content,
    helm_dash,
    loyalty,
    orders,
    payments,
    products,
    search,
    shipping,
    users,
    vessels,
)

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    # Startup
    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            environment=settings.app_env,
            release=f"helm-api@{app.version}",
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
            ],
        )

    yield

    # Shutdown — close connections, clean up resources


app = FastAPI(
    title="Helm Marine Platform API",
    description=(
        "New Zealand's smartest marine parts and fishing equipment platform. "
        "Provides vessel-aware product search, AI-powered First Mate assistant, "
        "Crew Rewards loyalty programme, and Helm Dash maritime delivery."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# Sentry error-capturing middleware
@app.middleware("http")
async def sentry_exception_middleware(request: Request, call_next):
    """Capture unhandled exceptions to Sentry."""
    try:
        return await call_next(request)
    except Exception as exc:
        if settings.sentry_dsn:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        logger.exception("Unhandled exception on %s %s", request.method, request.url)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all API routers under /api/v1
api_prefix = settings.api_v1_prefix

app.include_router(auth.router, prefix=api_prefix)
app.include_router(users.router, prefix=api_prefix)
app.include_router(vessels.router, prefix=api_prefix)
app.include_router(products.router, prefix=api_prefix)
app.include_router(search.router, prefix=api_prefix)
app.include_router(cart.router, prefix=api_prefix)
app.include_router(orders.router, prefix=api_prefix)
app.include_router(payments.router, prefix=api_prefix)
app.include_router(shipping.router, prefix=api_prefix)
app.include_router(ai.router, prefix=api_prefix)
app.include_router(checklists.router, prefix=api_prefix)
app.include_router(loyalty.router, prefix=api_prefix)
app.include_router(helm_dash.router, prefix=api_prefix)
app.include_router(content.router, prefix=api_prefix)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for monitoring and load balancers."""
    return {"status": "healthy", "service": "helm-api", "version": "0.1.0"}
