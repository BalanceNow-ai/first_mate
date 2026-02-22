"""Product Pydantic schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductBase(BaseModel):
    sku: str
    name: str
    description: str | None = None
    brand: str | None = None
    category: str
    sub_category: str | None = None
    price: float = Field(gt=0)
    sale_price: float | None = None
    weight_grams: int | None = None
    images: list[str] | None = None
    specifications: dict | None = None


class ProductCreate(ProductBase):
    cost_price: float | None = None
    stock_quantity: int = 0


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    brand: str | None = None
    category: str | None = None
    sub_category: str | None = None
    price: float | None = Field(None, gt=0)
    sale_price: float | None = None
    cost_price: float | None = None
    stock_quantity: int | None = None
    weight_grams: int | None = None
    images: list[str] | None = None
    specifications: dict | None = None
    is_active: bool | None = None


class ProductResponse(ProductBase):
    id: uuid.UUID
    cost_price: float | None = None
    stock_quantity: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductCompatibilityCreate(BaseModel):
    product_id: uuid.UUID
    vessel_make: str | None = None
    vessel_model: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine_make: str | None = None
    engine_model: str | None = None
    notes: str | None = None


class ProductCompatibilityResponse(ProductCompatibilityCreate):
    id: uuid.UUID

    model_config = {"from_attributes": True}


class CompatibilityCheck(BaseModel):
    is_compatible: bool
    message: str
