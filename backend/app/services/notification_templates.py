"""Notification templates: subject, plain text and minimal HTML, plus push title/body.

Payloads hold only what the message needs (order number, amounts in cents, status).
Rendering escapes every interpolated value for HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

from app.services.pricing import format_nzd

DELIVERY_STATUS_LABELS = {
    "awaiting_dispatch": "Awaiting dispatch",
    "assigned": "Skipper assigned",
    "accepted": "Skipper accepted your delivery",
    "picked_up": "Picked up from the warehouse",
    "en_route": "On the way to your vessel",
    "delivered": "Delivered",
    "failed": "Delivery could not be completed",
    "cancelled": "Delivery cancelled",
}
ORDER_STATUS_LABELS = {
    "dispatched": "Your order has been dispatched",
    "delivered": "Your order has been delivered",
    "collected": "Your order has been collected",
}
EXPERIENCE_STATUS_LABELS = {
    "requested": "We have received your experience request",
    "confirmed": "Your experience is confirmed",
    "fulfilled": "Your experience has been fulfilled",
    "cancelled": "Your experience redemption was cancelled and the points restored",
}
TEMPLATES = (
    "order_confirmed",
    "order_refunded",
    "order_status_changed",
    "helm_dash_status",
    "points_earned",
    "experience_redemption_updated",
    "service_reminder",
    "crew_invite",
)


@dataclass
class Rendered:
    subject: str
    text: str
    html: str
    push_title: str
    push_body: str


def _money(p: dict[str, Any], key: str) -> str:
    return format_nzd(int(p.get(key) or 0))


def _lines(template: str, p: dict[str, Any]) -> tuple[str, list[str], str]:
    """Return (subject, body lines, short push body)."""
    order = p.get("order_number", "")
    if template == "order_confirmed":
        lines = [f"Thanks for your order {order}.", f"Total paid: {_money(p, 'total_cents')} NZD."]
        if p.get("item_count"):
            lines.append(f"Items: {p['item_count']}.")
        if p.get("delivery_type") == "helm_dash":
            lines.append("We will let you know when a Helm Dash skipper is assigned.")
        elif p.get("delivery_type") == "click_and_collect":
            lines.append("We will tell you when it is ready to collect.")
        return f"Order {order} confirmed", lines, f"Order {order} confirmed"
    if template == "order_refunded":
        lines = [
            f"We have refunded {_money(p, 'refunded_now_cents')} NZD on order {order}.",
            f"Total refunded on this order: {_money(p, 'refunded_total_cents')} NZD.",
            "Refunds usually reach your card within 5-10 business days.",
        ]
        return f"Refund for order {order}", lines, f"Refund processed for order {order}"
    if template == "order_status_changed":
        label = ORDER_STATUS_LABELS.get(p.get("status", ""), "Your order has been updated")
        lines = [f"{label} (order {order})."]
        if p.get("tracking_number"):
            lines.append(f"Tracking number: {p['tracking_number']} ({p.get('courier') or 'courier'}).")
        return f"Order {order}: {label.lower()}", lines, f"{label} — {order}"
    if template == "helm_dash_status":
        label = DELIVERY_STATUS_LABELS.get(p.get("status", ""), "Delivery update")
        lines = [f"Helm Dash delivery for order {order}: {label}."]
        if p.get("operator_name") and p.get("status") in ("assigned", "accepted", "picked_up", "en_route"):
            lines.append(f"Your skipper: {p['operator_name']}.")
        return f"Helm Dash: {label}", lines, f"{label} — {order}"
    if template == "points_earned":
        pts = int(p.get("points") or 0)
        reason = p.get("reason") or "Crew Rewards"
        lines = [f"You earned {pts:,} Crew Points ({reason}).", f"Balance: {int(p.get('balance') or 0):,} CP."]
        return f"You earned {pts:,} Crew Points", lines, f"+{pts:,} CP — {reason}"
    if template == "experience_redemption_updated":
        label = EXPERIENCE_STATUS_LABELS.get(p.get("status", ""), "Experience redemption updated")
        lines = [f"{label}: {p.get('title', '')}.", f"Points: {int(p.get('points_cost') or 0):,} CP."]
        return f"Signature Experience: {label.lower()}", lines, label
    if template == "service_reminder":
        what = p.get("title", "Service")
        vessel = p.get("vessel_name") or "your vessel"
        lines = [f"Reminder: {what} is due for {vessel}."]
        if p.get("due_on"):
            lines.append(f"Due date: {p['due_on']}.")
        if p.get("due_engine_hours") is not None:
            lines.append(f"Due at {p['due_engine_hours']} engine hours (recorded: {p.get('engine_hours', 'unknown')}).")
        return f"Service due: {what}", lines, f"{what} is due for {vessel}"
    if template == "crew_invite":
        crew = p.get("crew_name", "a crew")
        inviter = p.get("inviter_name") or "A Helm customer"
        lines = [
            f'{inviter} has invited you to join the crew "{crew}" in Helm Crew Rewards.',
            "Sign in to Helm with this email address to accept or decline.",
            f"This invite expires on {p.get('expires_on', '')}.",
        ]
        return f"You're invited to join {crew}", lines, f"Invite to join {crew}"
    raise KeyError(template)


def render(template: str, payload: dict[str, Any]) -> Rendered:
    subject, lines, push_body = _lines(template, payload)
    text = "\n\n".join(lines) + "\n\n— Helm Marine\n"
    html = (
        '<!doctype html><html><body style="font-family:sans-serif;line-height:1.5">'
        + "".join(f"<p>{escape(line)}</p>" for line in lines)
        + "<p>— Helm Marine</p></body></html>"
    )
    return Rendered(subject=subject, text=text, html=html, push_title=subject, push_body=push_body)
