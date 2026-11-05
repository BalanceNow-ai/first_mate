"""Orders, order items, stock reservations and payment events."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, created_at_col, updated_at_col, uuid_pk

ORDER_STATUSES = (
    "pending_payment",  # stock reserved, awaiting successful payment
    "paid",  # payment confirmed by an authentic provider event
    "ready_for_dispatch",  # picked & packed
    "dispatched",  # handed to courier / Helm Dash operator
    "delivered",
    "collected",  # click & collect handed over
    "cancelled",  # cancelled before payment; reservation released
    "expired",  # reservation timed out; reservation released
    "refunded",  # fully refunded
    "payment_review",  # payment received but could not be applied (needs staff)
)
PAYMENT_STATUSES = (
    "unpaid",
    "requires_action",
    "processing",
    "failed",
    "succeeded",
    "partially_refunded",
    "refunded",
)
DELIVERY_TYPES = ("courier", "helm_dash", "click_and_collect")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in values) + ")"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        CheckConstraint(_in("status", ORDER_STATUSES), name="valid_status"),
        CheckConstraint(_in("payment_status", PAYMENT_STATUSES), name="valid_payment_status"),
        CheckConstraint(
            "delivery_type IS NULL OR " + _in("delivery_type", DELIVERY_TYPES),
            name="valid_delivery_type",
        ),
        CheckConstraint(
            "subtotal_cents >= 0 AND discount_cents >= 0 AND shipping_cents >= 0 "
            "AND total_cents >= 0 AND refunded_cents >= 0 AND refunded_cents <= total_cents",
            name="amounts_valid",
        ),
        CheckConstraint(
            "total_cents = subtotal_cents - discount_cents + shipping_cents", name="total_consistent"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending_payment")
    payment_status: Mapped[str] = mapped_column(
        String, nullable=False, default="unpaid", server_default="unpaid"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NZD", server_default="NZD")
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    shipping_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    refunded_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delivery_type: Mapped[str | None] = mapped_column(String, nullable=True)
    shipping_address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    helm_dash_coordinates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    delivery_quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_quotes.id", ondelete="SET NULL"), nullable=True
    )
    pickup_location: Mapped[str | None] = mapped_column(String, nullable=True)
    discount_entitlement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("discount_entitlements.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    payment_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    payment_intent_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String, nullable=True)
    courier: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    user: Mapped["User"] = relationship("User", back_populates="orders")  # noqa: F821
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.product_name"
    )
    reservations: Mapped[list["StockReservation"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("line_total_cents = unit_price_cents * quantity", name="line_total_consistent"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    sku: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    list_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="items")
    product: Mapped["Product"] = relationship("Product")  # noqa: F821


class StockReservation(Base):
    """Stock held for an order. Each transition happens exactly once."""

    __tablename__ = "stock_reservations"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "status IN ('reserved','consumed','released','restocked')", name="valid_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="reserved")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    order: Mapped[Order] = relationship(back_populates="reservations")


class PaymentEvent(Base):
    """Every provider webhook event received, for idempotency and audit."""

    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payment_intent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # applied | duplicate | ignored | mismatch | stale
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
