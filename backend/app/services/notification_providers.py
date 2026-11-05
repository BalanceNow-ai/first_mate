"""Notification delivery adapters (HTTP / SMTP boundary).

Email: ``resend`` (HTTP API), ``smtp_sink`` (local SMTP sink such as Mailpit; refused
outside development/test), ``log_sink`` (logs the outbox id and template only — never
the recipient or body), ``disabled`` (suppressed).

Push: ``fcm`` (HTTP v1 API with a service-account OAuth token; suppressed with a reason
when the project id / service account are not configured), ``log_sink``, ``disabled``.

Errors are reported as short machine codes (``resend_http_503``) so provider responses,
recipients and message bodies never reach logs or the outbox.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import time
from dataclasses import dataclass, field
from email.message import EmailMessage

import httpx
import jwt

from app.config import get_settings

logger = logging.getLogger(__name__)

# Tests replace this with an ``httpx.MockTransport`` to fake providers at the HTTP boundary.
http_transport: httpx.AsyncBaseTransport | None = None
_fcm_token: dict[str, object] = {}
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class Suppressed(Exception):  # noqa: N818 - an intentional non-send, not an error
    """The message is intentionally not sent (provider disabled / not configured)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProviderError(Exception):
    def __init__(self, code: str, *, permanent: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.permanent = permanent


@dataclass
class Email:
    to: str
    subject: str
    text: str
    html: str


@dataclass
class SendResult:
    provider: str
    message_id: str | None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=http_transport, timeout=get_settings().notification_http_timeout_seconds)


def _classify(prefix: str, status: int) -> ProviderError:
    transient = status in (408, 409, 425, 429) or status >= 500
    return ProviderError(f"{prefix}_http_{status}", permanent=not transient)


# ------------------------------------------------------------------------------ email
async def send_email(message: Email, *, outbox_id: str, template: str) -> SendResult:
    settings = get_settings()
    provider = settings.email_provider
    if provider == "disabled":
        raise Suppressed("email_disabled")
    if provider == "log_sink":
        logger.info("notification email outbox=%s template=%s provider=log_sink", outbox_id, template)
        return SendResult("log_sink", None)
    if provider == "smtp_sink":
        if not settings.is_local:
            raise Suppressed("smtp_sink_not_permitted")
        return await _smtp_sink(message, outbox_id)
    if provider == "resend":
        if not settings.resend_api_key:
            raise Suppressed("resend_not_configured")
        return await _resend(message, outbox_id)
    raise Suppressed("unknown_email_provider")


async def _resend(message: Email, outbox_id: str) -> SendResult:
    settings = get_settings()
    try:
        async with _client() as client:
            resp = await client.post(
                f"{settings.resend_api_url.rstrip('/')}/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Idempotency-Key": f"helm-outbox-{outbox_id}",
                },
                json={
                    "from": settings.resend_from_email,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.text,
                    "html": message.html,
                },
            )
    except httpx.HTTPError as exc:
        raise ProviderError(f"resend_{type(exc).__name__}") from None
    if resp.status_code >= 300:
        raise _classify("resend", resp.status_code)
    try:
        message_id = resp.json().get("id")
    except ValueError:
        message_id = None
    return SendResult("resend", message_id)


async def _smtp_sink(message: Email, outbox_id: str) -> SendResult:
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.resend_from_email
    msg["To"] = message.to
    msg["Subject"] = message.subject
    msg["X-Helm-Outbox-Id"] = outbox_id
    msg.set_content(message.text)
    msg.add_alternative(message.html, subtype="html")

    def _send() -> None:
        with smtplib.SMTP(settings.smtp_sink_host, settings.smtp_sink_port, timeout=10) as smtp:
            smtp.send_message(msg)

    try:
        await asyncio.to_thread(_send)
    except (OSError, smtplib.SMTPException) as exc:
        raise ProviderError(f"smtp_{type(exc).__name__}") from None
    return SendResult("smtp_sink", None)


# ------------------------------------------------------------------------------- push
@dataclass
class PushResult:
    """Per-device outcome of one push attempt (FM-04).

    ``sent`` maps token → provider message id; ``failed`` maps token → the error
    (``permanent`` or transient); ``invalid_tokens`` are unregistered devices."""

    provider: str
    message_ids: list[str]
    invalid_tokens: list[str]
    sent: dict[str, str] = field(default_factory=dict)
    failed: dict[str, ProviderError] = field(default_factory=dict)


async def send_push(
    tokens: list[str], *, title: str, body: str, data: dict[str, str], outbox_id: str, template: str
) -> PushResult:
    settings = get_settings()
    provider = settings.push_provider
    if provider == "disabled":
        raise Suppressed("push_disabled")
    if not tokens:
        raise Suppressed("no_push_device")
    if provider == "log_sink":
        logger.info(
            "notification push outbox=%s template=%s devices=%d provider=log_sink",
            outbox_id,
            template,
            len(tokens),
        )
        return PushResult("log_sink", [], [], sent={t: "" for t in tokens})
    if provider == "fcm":
        if not settings.firebase_project_id or not settings.firebase_service_account_json:
            raise Suppressed("fcm_not_configured")
        return await _fcm(tokens, title, body, data)
    raise Suppressed("unknown_push_provider")


def _service_account() -> dict:
    raw = get_settings().firebase_service_account_json
    try:
        info = json.loads(raw)
    except ValueError:
        try:
            with open(raw, encoding="utf-8") as fh:  # a path to the JSON key file
                info = json.load(fh)
        except (OSError, ValueError):
            raise Suppressed("fcm_service_account_invalid") from None
    if not all(k in info for k in ("client_email", "private_key")):
        raise Suppressed("fcm_service_account_invalid")
    return info


async def _fcm_access_token(client: httpx.AsyncClient) -> str:
    cached = _fcm_token.get("token")
    if cached and float(_fcm_token.get("exp", 0)) > time.time() + 60:  # type: ignore[arg-type]
        return str(cached)
    info = _service_account()
    token_uri = info.get("token_uri", "https://oauth2.googleapis.com/token")
    now = int(time.time())
    try:
        assertion = jwt.encode(
            {"iss": info["client_email"], "scope": FCM_SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600},
            info["private_key"],
            algorithm="RS256",
        )
    except Exception:  # noqa: BLE001 - malformed key
        raise Suppressed("fcm_service_account_invalid") from None
    try:
        resp = await client.post(
            token_uri,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
    except httpx.HTTPError as exc:
        raise ProviderError(f"fcm_oauth_{type(exc).__name__}") from None
    if resp.status_code >= 300:
        raise _classify("fcm_oauth", resp.status_code)
    body = resp.json()
    _fcm_token.update(token=body["access_token"], exp=now + int(body.get("expires_in", 3600)))
    return str(body["access_token"])


async def _fcm(tokens: list[str], title: str, body: str, data: dict[str, str]) -> PushResult:
    settings = get_settings()
    url = f"{settings.fcm_api_url.rstrip('/')}/v1/projects/{settings.firebase_project_id}/messages:send"
    sent: dict[str, str] = {}
    invalid: list[str] = []
    failed: dict[str, ProviderError] = {}
    async with _client() as client:
        access = await _fcm_access_token(client)
        for token in tokens:
            try:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access}"},
                    json={"message": {"token": token, "notification": {"title": title, "body": body}, "data": data}},
                )
            except httpx.HTTPError as exc:
                failed[token] = ProviderError(f"fcm_{type(exc).__name__}")
                continue
            if resp.status_code < 300:
                try:
                    sent[token] = str(resp.json().get("name", ""))
                except ValueError:
                    sent[token] = ""
            elif resp.status_code in (400, 404) and "UNREGISTERED" in resp.text:
                invalid.append(token)
            else:
                failed[token] = _classify("fcm", resp.status_code)
    # Every device's outcome is returned; the outbox persists them and retries only the
    # transiently failed devices (never re-sending to a device that already received it).
    return PushResult("fcm", list(sent.values()), invalid, sent=sent, failed=failed)
