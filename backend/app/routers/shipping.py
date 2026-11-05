"""Server-owned delivery quotes and options for the current cart."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import rate_limit, user_rate_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.schemas.shipping import (
    CourierDestination,
    DeliveryOptionsResponse,
    EstimateRequest,
    EstimateResponse,
    QuoteRequest,
    QuoteResponse,
)
from app.services import shipping_quotes

router = APIRouter(prefix="/shipping", tags=["Shipping & Quotes"])


@router.post(
    "/quotes",
    response_model=QuoteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(user_rate_limit("quote", lambda: get_settings().rate_limit_quote_per_minute))],
)
async def create_quote(
    body: QuoteRequest, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """Price the current cart for a delivery type and destination. The quote is bound to
    this user and cart, expires after ``QUOTE_TTL_MINUTES`` and can be used once."""
    is_courier_dest = isinstance(body.destination, CourierDestination)
    if is_courier_dest != (body.delivery_type == "courier"):
        raise AppError(
            422,
            "invalid_destination",
            "Courier quotes need {postcode}; Helm Dash quotes need {lat, lng}",
        )
    view = await shipping_quotes.create_quote(db, user_id, body.delivery_type, body.destination.model_dump())
    await db.commit()
    return shipping_quotes.quote_payload(view)


@router.get("/options", response_model=DeliveryOptionsResponse)
async def delivery_options(user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")) -> dict:
    """Which delivery types the current cart can use, with the reason when it cannot."""
    return await shipping_quotes.delivery_options(db, user_id)


@router.post(
    "/estimate",
    response_model=EstimateResponse,
    dependencies=[
        Depends(rate_limit("shipping_estimate", lambda: get_settings().rate_limit_shipping_estimate_per_minute))
    ],
)
async def estimate(body: EstimateRequest, db: AsyncSession = Depends(get_db, scope="function")) -> dict:
    """Public, informational price for product pages. Not a quote: it cannot be used at
    checkout (``bindable: false``)."""
    return await shipping_quotes.estimate(
        db,
        body.delivery_type,
        [(i.product_id, i.quantity) for i in body.items],
        body.destination.model_dump() if body.destination else None,
    )
