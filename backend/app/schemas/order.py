"""Order Pydantic schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrderItemCreate(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(ge=1)


class OrderItemResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: float

    model_config = {"from_attributes": True}


class OrderCreate(BaseModel):
    delivery_type: str = "courier"  # courier, helm_dash, click_and_collect
    shipping_address: dict | None = None
    helm_dash_coordinates: dict | None = None  # {lat, lng}
    notes: str | None = None


class OrderResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    subtotal: float
    shipping_cost: float
    total: float
    delivery_type: str | None
    shipping_address: dict | None
    tracking_number: str | None
    courier: str | None
    items: list[OrderItemResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderStatusUpdate(BaseModel):
    status: str
    tracking_number: str | None = None
    courier: str | None = None
