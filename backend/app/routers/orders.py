"""Orders: idempotent checkout, the customer's orders, cancellation and staff actions."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.core.rate_limit import mutation_limit, user_rate_limit
from app.database import get_db, utcnow
from app.middleware.auth import AdminUser, CurrentUserId, DispatcherUser
from app.models.order import DELIVERY_TYPES, ORDER_STATUSES, PAYMENT_STATUSES, Order, OrderItem
from app.models.shipping import CourierShipment, DeliveryQuote
from app.schemas.order import (
    CheckoutPreview,
    CheckoutRequest,
    FulfilmentUpdate,
    OrderListResponse,
    OrderResponse,
    RefundRequest,
    RefundResponse,
    ShipmentResponse,
    StaffOrderListResponse,
    StaffOrderResponse,
)
from app.services import audit, checkout, courier, order_lifecycle, payments, reservations

router = APIRouter(prefix="/orders", tags=["Orders"])

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_\-:.]{8,100}$")


def checkout_limit():
    return user_rate_limit("checkout", lambda: get_settings().rate_limit_checkout_per_minute)


# --------------------------------------------------------------------------- views
def _can_cancel(order: Order) -> bool:
    return order.status == "pending_payment" and order.payment_status not in (
        "processing",
        "succeeded",
    )


def _can_retry_payment(order: Order) -> bool:
    s = get_settings()
    return (
        order.status == "pending_payment"
        and order.payment_status in ("unpaid", "failed", "requires_action")
        and order.expires_at is not None
        and order.expires_at > utcnow()
        and s.payments_available
        and order.payment_provider == s.payment_provider
    )


async def _load_full(db: AsyncSession, order_id: uuid.UUID, *, user_id: uuid.UUID | None = None) -> Order | None:
    q = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    if user_id is not None:
        q = q.where(Order.user_id == user_id)
    return (await db.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()


async def order_view(db: AsyncSession, order: Order, *, staff: bool = False) -> dict:
    shipment = await courier.existing_shipment(db, order.id)
    quote = await db.get(DeliveryQuote, order.delivery_quote_id) if order.delivery_quote_id else None
    helm = order.helm_dash_coordinates
    data = {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "currency": order.currency,
        "subtotal_cents": order.subtotal_cents,
        "discount_cents": order.discount_cents,
        "shipping_cents": order.shipping_cents,
        "total_cents": order.total_cents,
        "refunded_cents": order.refunded_cents,
        "discount_entitlement_id": order.discount_entitlement_id,
        "payment_provider": order.payment_provider,
        "payment_intent_id": order.payment_intent_id,
        "delivery": {
            "delivery_type": order.delivery_type,
            "shipping_address": order.shipping_address,
            "helm_dash": helm,
            "pickup_location": order.pickup_location,
            "quote_id": order.delivery_quote_id,
            "service_name": quote.service_name if quote else None,
            "estimated_days": quote.estimated_days if quote else None,
            "estimated_minutes": quote.estimated_minutes if quote else None,
            "free_shipping_applied": bool(
                quote is not None
                and order.delivery_type == "courier"
                and order.shipping_cents == 0
                and quote.price_cents > 0
            ),
        },
        "items": [
            {
                "id": i.id,
                "product_id": i.product_id,
                "product_name": i.product_name,
                "sku": i.sku,
                "quantity": i.quantity,
                "list_price_cents": i.list_price_cents,
                "unit_price_cents": i.unit_price_cents,
                "line_total_cents": i.line_total_cents,
            }
            for i in order.items
        ],
        "expires_at": order.expires_at,
        "paid_at": order.paid_at,
        "cancelled_at": order.cancelled_at,
        "cancel_reason": order.cancel_reason,
        "notes": order.notes,
        "can_cancel": _can_cancel(order),
        "can_retry_payment": _can_retry_payment(order),
        "tracking": {
            "tracking_number": order.tracking_number,
            "courier": order.courier,
            "shipment_status": shipment.status if shipment else None,
            "is_test": bool(shipment and shipment.is_test),
        },
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }
    if staff:
        data.update(user_id=order.user_id, review_reason=order.review_reason)
    return data


def _summary(order: Order, item_count: int, *, staff: bool = False) -> dict:
    data = {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "currency": order.currency,
        "total_cents": order.total_cents,
        "refunded_cents": order.refunded_cents,
        "delivery_type": order.delivery_type,
        "item_count": item_count,
        "expires_at": order.expires_at,
        "created_at": order.created_at,
    }
    if staff:
        data.update(user_id=order.user_id, review_reason=order.review_reason)
    return data


async def _page(db: AsyncSession, q, page: int, page_size: int, *, staff: bool = False) -> dict:
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    orders = list(
        (
            await db.execute(
                q.order_by(Order.created_at.desc(), Order.id).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars()
    )
    counts: dict[uuid.UUID, int] = {}
    if orders:
        rows = await db.execute(
            select(OrderItem.order_id, func.sum(OrderItem.quantity))
            .where(OrderItem.order_id.in_([o.id for o in orders]))
            .group_by(OrderItem.order_id)
        )
        counts = {r[0]: int(r[1]) for r in rows}
    return {
        "items": [_summary(o, counts.get(o.id, 0), staff=staff) for o in orders],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _checkout_request(body: CheckoutRequest) -> checkout.CheckoutRequest:
    payments.ensure_card(body.payment_method)
    return checkout.CheckoutRequest(
        delivery_type=body.delivery_type,
        quote_id=body.quote_id,
        shipping_address=body.shipping_address.model_dump() if body.shipping_address else None,
        helm_dash_contact=body.helm_dash_contact.model_dump() if body.helm_dash_contact else None,
        discount_entitlement_id=body.discount_entitlement_id,
        notes=body.notes,
    )


# --------------------------------------------------------------------------- checkout
@router.post(
    "/checkout",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": OrderResponse, "description": "Existing order for this Idempotency-Key"}},
    dependencies=[Depends(checkout_limit())],
)
async def create_checkout(
    body: CheckoutRequest,
    response: Response,
    user_id: CurrentUserId,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Turn the cart into an order with stock reserved for ``RESERVATION_MINUTES``.

    Requires an ``Idempotency-Key`` header (8-100 chars of ``A-Z a-z 0-9 _ - : .``).
    Repeating a key returns the existing order (200) without side effects."""
    if idempotency_key is None or not IDEMPOTENCY_KEY.match(idempotency_key):
        raise AppError(
            400,
            "idempotency_key_required",
            "An Idempotency-Key header of 8-100 characters (letters, digits, _ - : .) is required",
        )
    req = _checkout_request(body)
    order, created = await checkout.checkout(db, user_id, req, idempotency_key)
    await db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    full = await _load_full(db, order.id)
    return await order_view(db, full)


@router.post(
    "/checkout/preview",
    response_model=CheckoutPreview,
    dependencies=[Depends(checkout_limit())],
)
async def preview_checkout(
    body: CheckoutRequest, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """The exact amounts checkout would charge for this body right now (no side effects)."""
    req = _checkout_request(body)
    pricing = await checkout.price_checkout(db, user_id, req)
    s = get_settings()
    await db.rollback()
    return {
        "delivery_type": req.delivery_type,
        "quote_id": req.quote_id,
        "subtotal_cents": pricing.subtotal_cents,
        "discount_cents": pricing.discount_cents,
        "shipping_cents": pricing.shipping_cents,
        "total_cents": pricing.total_cents,
        "free_shipping_applied": pricing.free_shipping_applied,
        "free_shipping_threshold_cents": s.free_shipping_threshold_cents,
        "min_charge_cents": s.min_charge_cents,
        "pickup_location": s.click_and_collect_location if req.delivery_type == "click_and_collect" else None,
    }


# --------------------------------------------------------------------------- customer
@router.get("/", response_model=OrderListResponse)
async def list_orders(
    user_id: CurrentUserId,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """The current user's orders, newest first."""
    return await _page(db, select(Order).where(Order.user_id == user_id), page, page_size)


@router.get("/admin/all", response_model=StaffOrderListResponse)
async def admin_list_orders(
    _staff: DispatcherUser,
    status_filter: str | None = Query(None, alias="status"),
    payment_status: str | None = Query(None),
    delivery_type: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    order_number: str | None = Query(None, max_length=40),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """All orders (dispatcher/admin) with optional filters."""
    for value, allowed, name in (
        (status_filter, ORDER_STATUSES, "status"),
        (payment_status, PAYMENT_STATUSES, "payment_status"),
        (delivery_type, DELIVERY_TYPES, "delivery_type"),
    ):
        if value is not None and value not in allowed:
            raise AppError(422, "invalid_filter", f"Unknown {name}: {value}")
    q = select(Order)
    if status_filter:
        q = q.where(Order.status == status_filter)
    if payment_status:
        q = q.where(Order.payment_status == payment_status)
    if delivery_type:
        q = q.where(Order.delivery_type == delivery_type)
    if user_id:
        q = q.where(Order.user_id == user_id)
    if order_number:
        q = q.where(Order.order_number.ilike(order_number.replace("%", "").replace("_", r"\_") + "%"))
    return await _page(db, q, page, page_size, staff=True)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """One of the current user's orders (404 for anyone else's, staff included; staff
    use ``GET /orders/admin/{order_id}``)."""
    order = await _load_full(db, order_id, user_id=user_id)
    if order is None:
        raise not_found("Order")
    return await order_view(db, order)


@router.post("/{order_id}/cancel", response_model=OrderResponse, dependencies=[Depends(mutation_limit())])
async def cancel_order(
    order_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """Cancel an unpaid order: releases the stock and restores the cart and discount."""
    order = await reservations.lock_order(db, order_id, user_id=user_id)
    if order is None:
        raise not_found("Order")
    if order.status != "pending_payment" or order.payment_status == "succeeded":
        raise AppError(409, "order_not_cancellable", f"A {order.status} order cannot be cancelled")
    if order.payment_status == "processing":
        raise AppError(409, "payment_processing", "This payment is being processed and cannot be cancelled now")
    released = await reservations.release_order(db, order, new_status="cancelled", reason="customer_cancelled")
    if not released:
        raise AppError(
            409,
            "payment_already_succeeded",
            "This order has been paid and can no longer be cancelled",
        )
    await db.commit()
    return await order_view(db, await _load_full(db, order.id))


# --------------------------------------------------------------------------- staff
async def _staff_order(db: AsyncSession, order_id: uuid.UUID) -> Order:
    order = await reservations.lock_order(db, order_id)
    if order is None:
        raise not_found("Order")
    return order


@router.get("/admin/{order_id}", response_model=StaffOrderResponse)
async def admin_get_order(
    order_id: uuid.UUID, _staff: DispatcherUser, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """Any order with staff fields (dispatcher/admin)."""
    order = await _load_full(db, order_id)
    if order is None:
        raise not_found("Order")
    return await order_view(db, order, staff=True)


@router.patch(
    "/{order_id}/fulfilment",
    response_model=StaffOrderResponse,
    dependencies=[Depends(mutation_limit())],
)
async def update_fulfilment(
    order_id: uuid.UUID,
    body: FulfilmentUpdate,
    staff: DispatcherUser,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Move a paid order through fulfilment (dispatcher/admin) using the shared state machine."""
    order = await _staff_order(db, order_id)
    previous = order.status
    await order_lifecycle.transition_fulfilment(
        db,
        order,
        body.status,
        actor_role=staff.role,
        tracking_number=body.tracking_number,
        courier=body.courier,
    )
    await audit.record(db, staff.id, "order_fulfilment", "order", order.id, {"from": previous, "to": body.status})
    await db.commit()
    return await order_view(db, await _load_full(db, order.id), staff=True)


@router.post(
    "/{order_id}/refund",
    response_model=RefundResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(mutation_limit())],
)
async def refund_order(
    order_id: uuid.UUID,
    body: RefundRequest,
    admin: AdminUser,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Request a refund from the provider (admin). The order's refunded amount changes
    when the provider's signed ``charge.refunded`` event is processed.

    Requires an ``Idempotency-Key`` header per refund request: repeating a key never
    refunds twice, while two separate refunds of the same amount use different keys."""
    if idempotency_key is None or not IDEMPOTENCY_KEY.match(idempotency_key):
        raise AppError(
            400,
            "idempotency_key_required",
            "An Idempotency-Key header of 8-100 characters (letters, digits, _ - : .) is required",
        )
    result = await payments.request_refund(db, admin, order_id, body.amount_cents, body.reason, idempotency_key)
    await db.commit()
    return result


@router.post(
    "/{order_id}/shipment",
    response_model=ShipmentResponse,
    dependencies=[Depends(mutation_limit())],
)
async def create_shipment(
    order_id: uuid.UUID,
    response: Response,
    staff: DispatcherUser,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> CourierShipment:
    """Book the courier label (dispatcher/admin). Development/test use the local contract
    adapter (test shipments only); live carrier booking answers 503."""
    order = await _staff_order(db, order_id)
    shipment, created = await courier.book_shipment(db, order)
    if created:
        await audit.record(
            db,
            staff.id,
            "courier_shipment_created",
            "order",
            order.id,
            {"provider": shipment.provider, "is_test": shipment.is_test},
        )
        response.status_code = status.HTTP_201_CREATED
    await db.commit()
    return shipment
