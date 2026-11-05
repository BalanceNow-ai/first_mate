"""Product and fitment schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.core.fitment_rules import rule_scope_problems
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

    @field_validator(
        "vessel_make",
        "vessel_model",
        "engine_make",
        "engine_model",
        "equipment_category",
        "equipment_make",
        "equipment_model",
        mode="before",
    )
    @classmethod
    def _blank_is_absent(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _well_formed_scope(self):
        """Every declared restriction needs its parent scope (FM-02); ranges are ordered."""
        problems = rule_scope_problems(self.model_dump())
        if problems:
            raise ValueError("Invalid fitment rule: " + "; ".join(problems))
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


class FitmentRuleAdminResponse(FitmentRuleResponse):
    equipment_category: str | None = None  # slug
    verified_by: uuid.UUID | None = None
    created_at: datetime


class FitmentRuleVerify(StrictInput):
    """Optional adjustments applied when an admin verifies a rule."""

    confidence_score: float | None = Field(None, ge=0, le=1)
    notes: str | None = None
    source_url: str | None = None


class FitmentRuleReject(StrictInput):
    notes: str | None = None


class StockAdjust(StrictInput):
    delta: int = Field(description="Signed change to stock_quantity (non-zero)")
    reason: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _non_zero(self):
        if self.delta == 0:
            raise ValueError("delta must not be zero")
        return self


class VesselRef(APIModel):
    id: uuid.UUID
    label: str


class ProductListResponse(APIModel):
    items: list[ProductResponse]
    total: int
    offset: int
    limit: int
    vessel: VesselRef | None = None


class AdminProductListResponse(APIModel):
    items: list[ProductAdminResponse]
    total: int
    offset: int
    limit: int


class SubCategoryCount(APIModel):
    name: str
    count: int


class CategoryCount(APIModel):
    category: str
    count: int
    sub_categories: list[SubCategoryCount] = []


class BrandCount(APIModel):
    brand: str
    count: int


class KnownFit(APIModel):
    """A verified fitment rule, presented as "known to fit"."""

    rule_id: uuid.UUID
    vessel_make: str | None
    vessel_model: str | None
    year_from: int | None
    year_to: int | None
    engine_make: str | None
    engine_model: str | None
    engine_year_from: int | None
    engine_year_to: int | None
    equipment_category: str | None
    equipment_make: str | None
    equipment_model: str | None
    fitment_type: str
    confidence_score: float
    data_source: str | None
    is_synthetic: bool
    notes: str | None


class CompatibilityResponse(APIModel):
    product_id: uuid.UUID
    sku: str
    fitment_scope: str
    universal: bool
    oem_part_numbers: list[str]
    known_to_fit: list[KnownFit]
