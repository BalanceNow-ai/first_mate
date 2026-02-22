"""Shipping rate Pydantic schemas."""

from pydantic import BaseModel


class ShippingRateRequest(BaseModel):
    destination_postcode: str
    weight_grams: int
    length_cm: int | None = None
    width_cm: int | None = None
    height_cm: int | None = None


class ShippingRate(BaseModel):
    provider: str  # nz_post, aramex
    service_name: str
    price_nzd: float
    estimated_days: int


class ShippingRatesResponse(BaseModel):
    rates: list[ShippingRate]
    cheapest: ShippingRate | None = None
