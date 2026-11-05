"""Shared helpers for the commerce / payments / shipping tests (no tests here).

Every helper goes through the real API with real signed tokens, or writes seed rows
directly where the tests need a precondition (entitlements, operating areas).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.config import get_settings
from app.database import async_session, utcnow
from app.models.cart import CartItem
from app.models.helm_dash import OperatingArea
from app.models.loyalty import DiscountEntitlement
from app.models.order import Order, PaymentEvent, StockReservation
from app.models.product import Product
from app.models.shipping import DeliveryQuote
from app.services.payments import sign_payload

API = "/api/v1"
ADDRESS = {
    "name": "Casey Customer",
    "line1": "1 Quay Street",
    "suburb": "Auckland Central",
    "city": "Auckland",
    "postcode": "1010",
    "phone": "+64 21 555 0101",
}
CONTACT = {"vessel_name": "Sea Biscuit", "phone": "021 555 0102", "note": "Pier C, berth 12"}
WAIHEKE = {"lat": -36.7900, "lng": 175.0100, "location_name": "Matiatia Bay"}
WELLINGTON = {"lat": -41.2900, "lng": 174.7800}


def idem() -> str:
    return f"test-{uuid.uuid4().hex}"


async def add(client, actor, product, qty: int = 1) -> dict:
    r = await client.post(
        f"{API}/cart/items",
        json={"product_id": str(product.id), "quantity": qty},
        headers=actor.headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def quote(client, actor, delivery_type: str = "courier", destination: dict | None = None):
    if destination is None:
        destination = {"postcode": "1010", "city": "Auckland"} if delivery_type == "courier" else WAIHEKE
    return await client.post(
        f"{API}/shipping/quotes",
        json={"delivery_type": delivery_type, "destination": destination},
        headers=actor.headers,
    )


async def checkout(client, actor, body: dict | None = None, key: str | None = None):
    body = body if body is not None else {"delivery_type": "click_and_collect"}
    headers = {**actor.headers, "Idempotency-Key": key or idem()}
    return await client.post(f"{API}/orders/checkout", json=body, headers=headers)


async def courier_checkout(client, actor, **extra):
    q = await quote(client, actor, "courier")
    assert q.status_code == 201, q.text
    body = {
        "delivery_type": "courier",
        "quote_id": q.json()["id"],
        "shipping_address": ADDRESS,
        **extra,
    }
    return await checkout(client, actor, body)


async def intent(client, actor, order_id: str):
    return await client.post(f"{API}/payments/orders/{order_id}/intent", json={}, headers=actor.headers)


async def confirm(client, actor, pi: str, outcome: str):
    return await client.post(f"{API}/payments/local/{pi}/confirm", json={"outcome": outcome}, headers=actor.headers)


async def pay(client, actor, order_id: str, outcome: str = "succeed") -> dict:
    r = await intent(client, actor, order_id)
    assert r.status_code == 200, r.text
    c = await confirm(client, actor, r.json()["payment_intent_id"], outcome)
    assert c.status_code == 200, c.text
    return c.json()


async def placed_order(client, actor, product, qty: int = 1, body: dict | None = None) -> dict:
    await add(client, actor, product, qty)
    r = await checkout(client, actor, body)
    assert r.status_code == 201, r.text
    return r.json()


async def paid_order(client, actor, product, qty: int = 1) -> dict:
    order = await placed_order(client, actor, product, qty)
    result = await pay(client, actor, order["id"])
    assert result["order_status"] == "paid", result
    return (await client.get(f"{API}/orders/{order['id']}", headers=actor.headers)).json()


# --------------------------------------------------------------------------- events
def pi_event(order: dict, event_type: str = "payment_intent.succeeded", *, event_id: str | None = None, **obj):
    status = {
        "payment_intent.succeeded": "succeeded",
        "payment_intent.payment_failed": "requires_payment_method",
        "payment_intent.canceled": "canceled",
        "payment_intent.processing": "processing",
        "payment_intent.requires_action": "requires_action",
    }.get(event_type, "succeeded")
    body = {
        "id": order["payment_intent_id"],
        "object": "payment_intent",
        "amount": order["total_cents"],
        "amount_received": order["total_cents"] if status == "succeeded" else 0,
        "currency": "nzd",
        "status": status,
        "metadata": {"order_id": order["id"], "order_number": order["order_number"]},
    }
    body.update(obj)
    return {
        "id": event_id or f"evt_test_{uuid.uuid4().hex}",
        "object": "event",
        "type": event_type,
        "created": int(time.time()),
        "data": {"object": body},
    }


def refund_event(order: dict, amount_refunded: int, *, event_id: str | None = None) -> dict:
    return {
        "id": event_id or f"evt_test_{uuid.uuid4().hex}",
        "object": "event",
        "type": "charge.refunded",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": f"ch_test_{order['id'][:8]}",
                "object": "charge",
                "amount": order["total_cents"],
                "amount_refunded": amount_refunded,
                "currency": "nzd",
                "payment_intent": order["payment_intent_id"],
                "metadata": {"order_id": order["id"]},
            }
        },
    }


async def post_event(client, event: dict, secret: str | None = None, signature: str | None = None):
    payload = json.dumps(event)
    secret = secret or get_settings().local_payment_webhook_secret
    sig = signature if signature is not None else sign_payload(payload, secret)
    headers = {"Content-Type": "application/json"}
    if sig:
        headers["Stripe-Signature"] = sig
    return await client.post(f"{API}/payments/webhook", content=payload, headers=headers)


# --------------------------------------------------------------------------- database
async def stock(product_id) -> int:
    async with async_session() as s:
        return (await s.execute(select(Product.stock_quantity).where(Product.id == product_id))).scalar_one()


async def db_order(order_id) -> Order:
    async with async_session() as s:
        return (await s.execute(select(Order).where(Order.id == uuid.UUID(str(order_id))))).scalar_one()


async def reservation_statuses(order_id) -> list[str]:
    async with async_session() as s:
        rows = await s.execute(
            select(StockReservation.status).where(StockReservation.order_id == uuid.UUID(str(order_id)))
        )
        return sorted(r[0] for r in rows)


async def cart_quantities(user_id) -> dict:
    async with async_session() as s:
        rows = await s.execute(select(CartItem.product_id, CartItem.quantity).where(CartItem.user_id == user_id))
        return {r[0]: r[1] for r in rows}


async def payment_events(order_id=None) -> list[PaymentEvent]:
    async with async_session() as s:
        q = select(PaymentEvent).order_by(PaymentEvent.created_at)
        if order_id is not None:
            q = q.where(PaymentEvent.order_id == uuid.UUID(str(order_id)))
        return list((await s.execute(q)).scalars())


async def seed_entitlement(user_id, amount_cents: int = 1000, status: str = "issued") -> DiscountEntitlement:
    async with async_session() as s:
        ent = DiscountEntitlement(
            user_id=user_id,
            code=f"CREW-{uuid.uuid4().hex[:8].upper()}",
            amount_cents=amount_cents,
            points_cost=amount_cents,
            status=status,
        )
        s.add(ent)
        await s.commit()
        await s.refresh(ent)
        return ent


async def entitlement(ent_id) -> DiscountEntitlement:
    async with async_session() as s:
        return (await s.execute(select(DiscountEntitlement).where(DiscountEntitlement.id == ent_id))).scalar_one()


async def seed_area(area_id: str = "hauraki-gulf", **overrides) -> OperatingArea:
    data = {
        "id": area_id,
        "name": "Hauraki Gulf",
        "center_lat": -36.80,
        "center_lng": 174.90,
        "radius_nm": 30.0,
        "enabled": True,
    }
    data.update(overrides)
    async with async_session() as s:
        area = OperatingArea(**data)
        s.add(area)
        await s.commit()
        return area


async def expire_order(order_id, minutes: int = 1) -> None:
    async with async_session() as s:
        await s.execute(
            update(Order)
            .where(Order.id == uuid.UUID(str(order_id)))
            .values(expires_at=utcnow() - timedelta(minutes=minutes))
        )
        await s.commit()


async def expire_quote(quote_id) -> None:
    async with async_session() as s:
        await s.execute(
            update(DeliveryQuote)
            .where(DeliveryQuote.id == uuid.UUID(str(quote_id)))
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()


class EventSpy:
    """Counts calls to a services.events hook while still running it."""

    def __init__(self, monkeypatch, name: str = "order_paid") -> None:
        from app.services import events

        self.calls: list[uuid.UUID] = []
        original = getattr(events, name)

        async def wrapper(db, order, *args):
            self.calls.append(order.id)
            return await original(db, order, *args)

        monkeypatch.setattr(events, name, wrapper)
