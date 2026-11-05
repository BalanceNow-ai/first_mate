"""Shared builders for the rewards / Helm Dash / notification tests (no tests here).

Orders are written straight to PostgreSQL in the state the commerce workflow leaves
them in, then the real domain events (``services.events``) are raised.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import async_session, utcnow
from app.models.helm_dash import DeliveryOperator, HelmDashDelivery, OperatingArea
from app.models.loyalty import CrewTeam, CrewTeamMember
from app.models.order import Order
from app.models.shipping import DeliveryQuote
from app.services import events, loyalty

AREA_ID = "hauraki-gulf"


async def make_order(
    user_id: uuid.UUID,
    *,
    subtotal_cents: int = 10_000,
    discount_cents: int = 0,
    shipping_cents: int = 0,
    paid_at: datetime | None = None,
    payment_status: str = "succeeded",
    status: str = "paid",
    delivery_type: str = "courier",
    helm_dash_coordinates: dict | None = None,
    delivery_quote_id: uuid.UUID | None = None,
) -> Order:
    async with async_session() as s:
        order = Order(
            order_number=f"HM-{uuid.uuid4().hex[:8].upper()}",
            user_id=user_id,
            status=status,
            payment_status=payment_status,
            subtotal_cents=subtotal_cents,
            discount_cents=discount_cents,
            shipping_cents=shipping_cents,
            total_cents=subtotal_cents - discount_cents + shipping_cents,
            delivery_type=delivery_type,
            helm_dash_coordinates=helm_dash_coordinates,
            delivery_quote_id=delivery_quote_id,
            idempotency_key=uuid.uuid4().hex,
            paid_at=paid_at if paid_at is not None else (utcnow() if payment_status != "unpaid" else None),
        )
        s.add(order)
        await s.commit()
        await s.refresh(order)
        return order


async def pay(order: Order) -> Order:
    """Raise the real ``order_paid`` event (as the payment webhook would)."""
    async with async_session() as s:
        o = await s.get(Order, order.id)
        await events.order_paid(s, o)
        await s.commit()
        await s.refresh(o)
        return o


async def paid_order(user_id: uuid.UUID, **kw) -> Order:
    return await pay(await make_order(user_id, **kw))


async def refund(order_id: uuid.UUID, amount_cents: int) -> Order:
    async with async_session() as s:
        o = (await s.execute(select(Order).where(Order.id == order_id).with_for_update())).scalar_one()
        o.refunded_cents += amount_cents
        o.payment_status = "refunded" if o.refunded_cents >= o.total_cents else "partially_refunded"
        if o.payment_status == "refunded":
            o.status = "refunded"
        await s.flush()
        await events.order_refunded(s, o, amount_cents)
        await s.commit()
        return o


async def replay_refund_event(order_id: uuid.UUID, amount_cents: int) -> None:
    """Deliver the same refund event again (duplicate webhook)."""
    async with async_session() as s:
        o = await s.get(Order, order_id)
        await events.order_refunded(s, o, amount_cents)
        await s.commit()


async def balance(user_id: uuid.UUID) -> int:
    async with async_session() as s:
        acct = await loyalty.lock_account(s, user_id)
        await s.commit()
        return acct.points_balance


async def grant_points(user_id: uuid.UUID, points: int) -> None:
    async with async_session() as s:
        await loyalty.apply(
            s, user_id=user_id, kind="adjustment", points=points, idempotency_key=f"test-grant:{uuid.uuid4()}"
        )
        await s.commit()


async def make_crew(captain_id: uuid.UUID, *member_ids: uuid.UUID, name: str = "Test Crew") -> uuid.UUID:
    async with async_session() as s:
        team = CrewTeam(name=name, created_by=captain_id)
        s.add(team)
        await s.flush()
        s.add(CrewTeamMember(team_id=team.id, user_id=captain_id, role="captain", joined_at=utcnow()))
        for i, uid in enumerate(member_ids):
            s.add(
                CrewTeamMember(
                    team_id=team.id, user_id=uid, role="member", joined_at=utcnow() + timedelta(seconds=i + 1)
                )
            )
        await s.commit()
        return team.id


async def make_area(area_id: str = AREA_ID, enabled: bool = True) -> None:
    async with async_session() as s:
        s.add(
            OperatingArea(
                id=area_id,
                name=area_id.replace("-", " ").title(),
                center_lat=-36.8,
                center_lng=174.9,
                radius_nm=25,
                enabled=enabled,
            )
        )
        await s.commit()


async def make_operator_profile(
    user_id: uuid.UUID, area_id: str = AREA_ID, active: bool = True, name: str = "Skipper Sam"
) -> None:
    async with async_session() as s:
        s.add(
            DeliveryOperator(user_id=user_id, display_name=name, vessel_name="Dash One", area_id=area_id, active=active)
        )
        await s.commit()


async def helm_dash_order(user_id: uuid.UUID, area_id: str = AREA_ID, price_cents: int = 4900) -> Order:
    async with async_session() as s:
        quote = DeliveryQuote(
            user_id=user_id,
            delivery_type="helm_dash",
            provider="helm_dash",
            service_name="Helm Dash",
            price_cents=price_cents,
            destination={"lat": -36.80, "lng": 174.95},
            parcel_weight_grams=2000,
            cart_fingerprint="fp",
            operating_area_id=area_id,
            nautical_miles=Decimal("3.00"),
            estimated_minutes=35,
            expires_at=utcnow() + timedelta(minutes=20),
        )
        s.add(quote)
        await s.commit()
        quote_id = quote.id
    return await make_order(
        user_id,
        subtotal_cents=12_000,
        shipping_cents=price_cents,
        delivery_type="helm_dash",
        helm_dash_coordinates={"lat": -36.80, "lng": 174.95, "name": "Rangitoto Channel mooring"},
        delivery_quote_id=quote_id,
    )


async def delivery_for(order_id: uuid.UUID) -> HelmDashDelivery | None:
    async with async_session() as s:
        return (
            await s.execute(select(HelmDashDelivery).where(HelmDashDelivery.order_id == order_id))
        ).scalar_one_or_none()
