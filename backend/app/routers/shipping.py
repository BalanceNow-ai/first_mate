"""Shipping rate calculation router (NZ Post + Aramex)."""

from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.schemas.shipping import ShippingRate, ShippingRateRequest, ShippingRatesResponse

router = APIRouter(prefix="/shipping", tags=["Shipping"])
settings = get_settings()


async def _get_nzpost_rate(request: ShippingRateRequest) -> ShippingRate | None:
    """Fetch shipping rate from NZ Post API.

    In production, this calls the NZ Post Rate Card API.
    Returns a fallback rate structure for development.
    """
    if not settings.nzpost_client_id:
        # Development fallback rates based on weight
        weight_kg = request.weight_grams / 1000
        if weight_kg <= 1:
            price = 7.50
        elif weight_kg <= 5:
            price = 12.90
        elif weight_kg <= 15:
            price = 18.50
        else:
            price = 29.90

        return ShippingRate(
            provider="nz_post",
            service_name="NZ Post CourierPost",
            price_nzd=price,
            estimated_days=2,
        )

    # TODO: Implement actual NZ Post API call
    # Use httpx to call https://api.nzpost.co.nz/ratecard/v1/rates
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.nzpost.co.nz/ratecard/v1/rates",
                headers={"Authorization": f"Bearer {settings.nzpost_client_id}"},
                json={
                    "destination_postcode": request.destination_postcode,
                    "weight_grams": request.weight_grams,
                    "length_cm": request.length_cm,
                    "width_cm": request.width_cm,
                    "height_cm": request.height_cm,
                },
            )
            if response.status_code == 200:
                data = response.json()
                return ShippingRate(
                    provider="nz_post",
                    service_name=data.get("service_name", "NZ Post CourierPost"),
                    price_nzd=data.get("price", 12.90),
                    estimated_days=data.get("estimated_days", 2),
                )
    except Exception:
        pass

    return None


async def _get_aramex_rate(request: ShippingRateRequest) -> ShippingRate | None:
    """Fetch shipping rate from Aramex NZ API.

    In production, this calls the Aramex rate API.
    Returns a fallback rate structure for development.
    """
    if not settings.aramex_api_key:
        # Development fallback rates
        weight_kg = request.weight_grams / 1000
        if weight_kg <= 1:
            price = 8.20
        elif weight_kg <= 5:
            price = 13.50
        elif weight_kg <= 15:
            price = 19.90
        else:
            price = 32.00

        return ShippingRate(
            provider="aramex",
            service_name="Aramex Fastway Couriers",
            price_nzd=price,
            estimated_days=3,
        )

    # TODO: Implement actual Aramex API call
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.aramex.co.nz/api/rate",
                headers={"api-key": settings.aramex_api_key},
                json={
                    "destination_postcode": request.destination_postcode,
                    "weight_grams": request.weight_grams,
                },
            )
            if response.status_code == 200:
                data = response.json()
                return ShippingRate(
                    provider="aramex",
                    service_name=data.get("service_name", "Aramex Fastway"),
                    price_nzd=data.get("price", 13.50),
                    estimated_days=data.get("estimated_days", 3),
                )
    except Exception:
        pass

    return None


@router.post("/rates", response_model=ShippingRatesResponse)
async def calculate_shipping_rates(
    request: ShippingRateRequest,
) -> ShippingRatesResponse:
    """Calculate shipping rates from both NZ Post and Aramex.

    Returns rates from both providers and identifies the cheapest option.
    """
    rates: list[ShippingRate] = []

    nzpost_rate = await _get_nzpost_rate(request)
    if nzpost_rate:
        rates.append(nzpost_rate)

    aramex_rate = await _get_aramex_rate(request)
    if aramex_rate:
        rates.append(aramex_rate)

    if not rates:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to calculate shipping rates at this time",
        )

    cheapest = min(rates, key=lambda r: r.price_nzd)

    return ShippingRatesResponse(rates=rates, cheapest=cheapest)
