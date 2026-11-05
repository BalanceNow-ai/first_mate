"""Product and fitment schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import APIModel, StrictInput

FitmentStatus = Literal["verified_fit", "verified_mismatch", "unknown", "universal"]


class FitmentResult(APIModel):
    """Outcome of the central fitment evaluation for one product and one vessel."""

    status: FitmentStatus
    vessel_id: uuid.UUID | None = None
    message: str
    reasons: list[str] = []
    matched_rule_ids: list[uuid.UUID] = []


class ProductResponse(APIModel):
    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    brand: str | None
    category: str
    sub_category: str | None
    currency: str = "NZD"
    price_cents: int
    sale_price_cents: int | None
    effective_price_cents: int
    on_sale: bool
    stock_quantity: int
    in_stock: bool
    weight_grams: int | None
    images: list[str] = []
    specifications: dict | None
    oem_part_numbers: list[str] = []
    part_role: str | None
    fitment_scope: str
    dangerous_goods: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    fitment: FitmentResult | None = None


class ProductAdminResponse(ProductResponse):
    cost_price_cents: int | None


class ProductCreate(StrictInput):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    brand: str | None = None
    category: str = Field(min_length=1)
    sub_category: str | None = None
    price_cents: int = Field(gt=0)
    sale_price_cents: int | None = Field(None, gt=0)
    cost_price_cents: int | None = Field(None, ge=0)
    stock_quantity: int = Field(0, ge=0)
    weight_grams: int | None = Field(None, ge=0)
    images: list[str] | None = None
    specifications: dict | None = None
    oem_part_numbers: list[str] = []
    part_role: str | None = None
    fitment_scope: Literal["universal", "specific", "unspecified"] = "unspecified"
    dangerous_goods: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def _sale_below_price(self):
        if self.sale_price_cents is not None and self.sale_price_cents >= self.price_cents:
            raise ValueError("sale_price_cents must be lower than price_cents")
        return self


class ProductUpdate(StrictInput):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    brand: str | None = None
    category: str | None = None
    sub_category: str | None = None
    price_cents: int | None = Field(None, gt=0)
    sale_price_cents: int | None = Field(None, gt=0)
    cost_price_cents: int | None = Field(None, ge=0)
    stock_quantity: int | None = Field(None, ge=0)
    weight_grams: int | None = Field(None, ge=0)
    images: list[str] | None = None
    specifications: dict | None = None
    oem_part_numbers: list[str] | None = None
    part_role: str | None = None
    fitment_scope: Literal["universal", "specific", "unspecified"] | None = None
    dangerous_goods: bool | None = None
    is_active: bool | None = None


class FitmentRuleCreate(StrictInput):
    vessel_make: str | None = None
    vessel_model: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine_make: str | None = None
    engine_model: str | None = None
    engine_year_from: int | None = None
    engine_year_to: int | None = None
    equipment_category: str | None = None  # equipment category slug
    equipment_make: str | None = None
    equipment_model: str | None = None
    fitment_type: Literal["service_part", "consumable", "upgrade", "accessory"] = "service_part"
    data_source: str | None = None
    source_url: str | None = None
    confidence_score: float = Field(0.3, ge=0, le=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _has_scope(self):
        if not (self.vessel_make or self.engine_make or self.equipment_category):
            raise ValueError("A fitment rule needs a vessel, engine or equipment scope")
        return self


class FitmentRuleResponse(APIModel):
    id: uuid.UUID
    product_id: uuid.UUID
    vessel_make: str | None
    vessel_model: str | None
    year_from: int | None
    year_to: int | None
    engine_make: str | None
    engine_model: str | None
    engine_year_from: int | None
    engine_year_to: int | None
    equipment_category_id: uuid.UUID | None
    equipment_make: str | None
    equipment_model: str | None
    fitment_type: str
    verification_status: str
    confidence_score: float
    data_source: str | None
    source_url: str | None
    notes: str | None
    verified_at: datetime | None
