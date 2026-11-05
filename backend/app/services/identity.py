"""Server-side identity checks against the Supabase Auth Admin API.

Token claims prove *who* the caller is; they do not reliably prove that the email was
confirmed (``user_metadata`` is user-editable). When ``SUPABASE_SERVICE_ROLE_KEY`` is
configured (required outside development/test), provisioning asks the Admin API for the
user's ``email_confirmed_at`` and refuses unconfirmed emails.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

import httpx

from app.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)
_transport: httpx.AsyncBaseTransport | None = None  # test hook (fake at the HTTP boundary)


async def confirmed_email(user_id: uuid.UUID) -> tuple[str | None, datetime | None] | None:
    """Return (email, email_confirmed_at) from the Admin API, or None when not configured."""
    s = get_settings()
    if not (s.supabase_service_role_key and s.supabase_url):
        return None
    url = f"{s.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}"
    headers = {"apikey": s.supabase_service_role_key, "Authorization": f"Bearer {s.supabase_service_role_key}"}
    try:
        async with httpx.AsyncClient(timeout=5.0, transport=_transport) as client:
            r = await client.get(url, headers=headers)
    except httpx.HTTPError:
        logger.error("Supabase Admin API unreachable during provisioning")
        raise AppError(503, "identity_unavailable", "Account verification is temporarily unavailable") from None
    if r.status_code != 200:
        logger.error("Supabase Admin API returned %s during provisioning", r.status_code)
        raise AppError(503, "identity_unavailable", "Account verification is temporarily unavailable")
    body = r.json()
    raw = body.get("email_confirmed_at") or body.get("confirmed_at")
    confirmed = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
    email = body.get("email")
    return (email.lower() if isinstance(email, str) else None), confirmed
