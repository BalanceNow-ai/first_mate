"""Private evidence and invoice media (spec §5.2, §5.3, §10, §12; SJ-07, SJ-19, SJ-21).

Life cycle of an :class:`EvidenceAsset`::

    upload intent (upload_pending) ─PUT content→ quarantined ─claim→ processing ─publish→ available
                                                                        └→ rejected / back to quarantined
    any state ─delete→ deleted (objects purged, key tombstoned)

* **Intents** are tied to the job (or the owner, for a standalone invoice), the uploading
  actor, the media purpose and a maximum size. Per-job asset count / combined bytes and the
  per-owner storage quota are reserved at intent time (pending intents reserve their
  ``max_bytes``) under the job row lock plus a per-owner advisory lock.
* **Content** is streamed, bounded server-side, hashed, and written to an opaque
  ``quarantine/`` key. Receipt is claimed with a short lease so a repeated/concurrent PUT
  cannot overwrite bytes another request already hashed.
* **Processing** claims the asset with a short ``UPDATE … RETURNING`` (lease + fencing
  token + attempts) and commits; scanning, type detection, decoding and derivative work run
  with no transaction open; publication re-locks job → asset and checks the token, so a
  worker whose lease expired (crash, stall) can never publish. Scanner failure, storage
  failure or timeout returns the asset to ``quarantined`` — never ``available``.
* Type is detected from magic bytes only (JPEG, PNG, WebP, HEIC, PDF); the extension and
  client MIME type are ignored. Images are decoded under a pixel limit, orientation-
  corrected, and re-encoded as a metadata-free JPEG derivative (no EXIF/GPS/XMP/ICC).
  PDFs are validated inertly with pypdf (page limit; encrypted, JavaScript, OpenAction,
  additional actions, Launch, embedded files, XFA, rich media and form-submission
  content rejected) and re-written page-by-page without document metadata. PDFs are only
  ever served as attachments.
* Capture-quality hints (blur, darkness) are advisory; framing and label legibility are
  ``not_assessed``. Nothing here reads or invents text.
* Duplicates within a job (exact SHA-256, or a perceptual dHash within a small Hamming
  distance) are marked ``duplicate_of_id`` and are not extra evidence.

Other capabilities read media only through :func:`derivative_bytes` (derivatives, never
originals or metadata) and authorise downloads through :func:`resolve` /
:func:`signed_download`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import BytesIO

import pillow_heif
from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError
from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.ops import AuditLog
from app.models.service_jobs import (
    EvidenceAsset,
    EvidenceRequest,
    Invoice,
    InvoiceRevision,
    JobAssignment,
    ModerationCase,
    ServiceJob,
)
from app.services import audit
from app.services.service_jobs import access, revisions, scanner, storage
from app.services.service_jobs.notify import notify

logger = logging.getLogger(__name__)

pillow_heif.register_heif_opener()

JPEG, PNG, WEBP, HEIC, PDF = "image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"
IMAGE_TYPES = frozenset({JPEG, PNG, WEBP, HEIC})
PURPOSE_TYPES = {
    "job_photo": IMAGE_TYPES,
    "job_document": IMAGE_TYPES | {PDF},
    "invoice": IMAGE_TYPES | {PDF},
}
JOB_PURPOSES = ("job_photo", "job_document")
# Assets that hold (or reserve) storage and count towards the per-job asset limit.
COUNTED_STATUSES = ("upload_pending", "quarantined", "processing", "available")
TOMBSTONE_PREFIX = "deleted/"
DERIVATIVE_MAX_EDGE = 4096
PHASH_MAX_DISTANCE = 4
BLUR_VARIANCE_THRESHOLD = 60.0
DARK_MEAN_THRESHOLD = 40.0
PDF_MAX_OBJECTS = 50_000
RETENTION_NOTICE_DAYS = 14
_PIL_FORMAT = {JPEG: "JPEG", PNG: "PNG", WEBP: "WEBP", HEIC: "HEIF"}
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


# --------------------------------------------------------------------------- helpers
def purpose_max_bytes(purpose: str) -> int:
    settings = get_settings()
    if purpose == "job_photo":
        return settings.service_image_max_bytes
    return max(settings.service_image_max_bytes, settings.service_pdf_max_bytes)


def type_max_bytes(detected: str) -> int:
    settings = get_settings()
    return settings.service_pdf_max_bytes if detected == PDF else settings.service_image_max_bytes


def derivative_media_type(asset: EvidenceAsset) -> str:
    return PDF if asset.detected_type == PDF else JPEG


def download_filename(asset: EvidenceAsset, variant: str) -> str:
    """Server-generated names only (never the declared filename)."""
    stem = {"invoice": "invoice", "job_document": "document"}.get(asset.purpose, "photo")
    if variant == "original":
        ext = {JPEG: "jpg", PNG: "png", WEBP: "webp", HEIC: "heic", PDF: "pdf"}.get(asset.detected_type or "", "bin")
        return f"{stem}-{asset.id.hex[:8]}-original.{ext}"
    return f"{stem}-{asset.id.hex[:8]}.{'pdf' if asset.detected_type == PDF else 'jpg'}"


def _clean_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = "".join(ch for ch in value if ch.isprintable()).strip()
    return value[:limit] or None


def _owner_lock(owner_id: uuid.UUID):
    return select(func.pg_advisory_xact_lock(func.hashtext(f"service_assets_owner:{owner_id}")))


async def _lock_job(db: AsyncSession, job_id: uuid.UUID) -> ServiceJob | None:
    return (
        await db.execute(
            select(ServiceJob)
            .where(ServiceJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _lock_asset(db: AsyncSession, asset_id: uuid.UUID) -> EvidenceAsset | None:
    return (
        await db.execute(
            select(EvidenceAsset)
            .where(EvidenceAsset.id == asset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def enqueue_processing(asset_id: uuid.UUID) -> bool:
    """Queue processing after the receipt committed. A broker outage is logged, never
    raised: the recovery sweep picks up quarantined assets that were never processed."""
    try:
        from app.celery_app import celery

        celery.send_task("app.tasks.service_media.process_asset", args=[str(asset_id)], retry=False, ignore_result=True)
        return True
    except Exception as exc:  # pragma: no cover - broker outage
        logger.error("Could not queue media processing: %s", type(exc).__name__)
        return False


async def purge_objects(db: AsyncSession, asset_id: uuid.UUID, keys: list[str]) -> bool:
    """Delete a deleted asset's objects (no transaction open while calling storage), then
    tombstone its keys. Failures are left for the retention sweep. Commits."""
    await db.commit()
    store = storage.get_store()
    try:
        for key in keys:
            if key and not key.startswith(TOMBSTONE_PREFIX):
                await asyncio.to_thread(store.delete, key)
    except storage.ObjectStoreError:
        logger.warning("Object deletion deferred for asset %s", asset_id)
        return False
    await db.execute(
        update(EvidenceAsset)
        .where(EvidenceAsset.id == asset_id, EvidenceAsset.status == "deleted")
        .values(storage_key=f"{TOMBSTONE_PREFIX}{asset_id}", derivative_key=None)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return True


# --------------------------------------------------------------------------- intents
async def _replay(
    db: AsyncSession, owner_id: uuid.UUID, user_id: uuid.UUID, key: str | None, *, purpose: str, job_id
) -> EvidenceAsset | None:
    if key is None:
        return None
    existing = (
        await db.execute(
            select(EvidenceAsset).where(
                EvidenceAsset.owner_id == owner_id, EvidenceAsset.idempotency_key == f"{user_id}:{key}"
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return None
    if existing.purpose != purpose or existing.job_id != job_id or existing.uploaded_by != user_id:
        raise AppError(409, "idempotency_key_reused", "This Idempotency-Key was already used for another upload")
    return existing


def check_idempotency_key(key: str | None) -> str | None:
    if key is None or key == "":
        return None
    if not _IDEMPOTENCY_KEY.match(key):
        raise AppError(422, "invalid_idempotency_key", "Idempotency-Key must be 8–128 letters, digits or -_.:")
    return key


async def _reserve(db: AsyncSession, owner_id: uuid.UUID, job: ServiceJob | None, reserve: int) -> None:
    """Enforce per-job count/bytes and the per-owner quota. Caller holds the job row lock."""
    settings = get_settings()
    await db.execute(_owner_lock(owner_id))
    held = func.coalesce(
        func.sum(
            case((EvidenceAsset.size_bytes.is_not(None), EvidenceAsset.size_bytes), else_=EvidenceAsset.max_bytes)
        ),
        0,
    )
    if job is not None:
        count, total = (
            await db.execute(
                select(func.count(EvidenceAsset.id), held).where(
                    EvidenceAsset.job_id == job.id, EvidenceAsset.status.in_(COUNTED_STATUSES)
                )
            )
        ).one()
        if count >= settings.service_job_max_assets:
            raise AppError(
                409,
                "asset_limit_reached",
                f"This job already has the maximum of {settings.service_job_max_assets} files",
            )
        if total + reserve > settings.service_job_max_total_bytes:
            raise AppError(409, "job_storage_limit", "This job has reached its storage limit")
    owner_total = (
        await db.execute(
            select(held).where(EvidenceAsset.owner_id == owner_id, EvidenceAsset.status.in_(COUNTED_STATUSES))
        )
    ).scalar_one()
    if owner_total + reserve > settings.service_owner_storage_bytes:
        raise AppError(409, "storage_quota_exceeded", "The storage quota for this account has been reached")


async def _new_intent(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    job: ServiceJob | None,
    uploaded_by: uuid.UUID,
    organization_id: uuid.UUID | None,
    purpose: str,
    evidence_request_id: uuid.UUID | None,
    caption: str | None,
    filename: str | None,
    content_type: str | None,
    size_bytes: int | None,
    idempotency_key: str | None,
) -> EvidenceAsset:
    settings = get_settings()
    limit = purpose_max_bytes(purpose)
    if size_bytes is not None and size_bytes > limit:
        raise AppError(
            413, "file_too_large", f"Files for this purpose may be at most {limit} bytes", extra={"max_bytes": limit}
        )
    max_bytes = min(limit, size_bytes) if size_bytes else limit
    await _reserve(db, owner_id, job, max_bytes)
    asset = EvidenceAsset(
        owner_id=owner_id,
        job_id=job.id if job else None,
        uploaded_by=uploaded_by,
        uploader_organization_id=organization_id,
        purpose=purpose,
        evidence_request_id=evidence_request_id,
        caption=_clean_text(caption, 500),
        declared_filename=_clean_text(filename, 200),
        declared_content_type=_clean_text(content_type, 100),
        max_bytes=max_bytes,
        storage_key=storage.new_key("quarantine"),
        status="upload_pending",
        upload_expires_at=utcnow() + timedelta(hours=settings.service_upload_intent_hours),
        idempotency_key=f"{uploaded_by}:{idempotency_key}" if idempotency_key else None,
    )
    db.add(asset)
    await db.flush()
    return asset


async def create_job_intent(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    purpose: str,
    evidence_request_id: uuid.UUID | None = None,
    caption: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    size_bytes: int | None = None,
    idempotency_key: str | None = None,
) -> tuple[EvidenceAsset, bool]:
    """Owner, or the assigned contractor with the ``evidence`` section. Returns (asset, created)."""
    if purpose not in JOB_PURPOSES:
        raise AppError(422, "invalid_purpose", "Job uploads are job_photo or job_document")
    actor = await access.job_for(db, user_id, job_id, section="evidence", lock=True)
    job = actor.job
    replay = await _replay(db, job.owner_id, user_id, idempotency_key, purpose=purpose, job_id=job.id)
    if replay is not None:
        return replay, False
    if evidence_request_id is not None:
        request = (
            await db.execute(
                select(EvidenceRequest.id).where(
                    EvidenceRequest.id == evidence_request_id, EvidenceRequest.job_id == job.id
                )
            )
        ).scalar_one_or_none()
        if request is None:
            raise not_found("Evidence request")
    asset = await _new_intent(
        db,
        owner_id=job.owner_id,
        job=job,
        uploaded_by=user_id,
        organization_id=actor.organization_id,
        purpose=purpose,
        evidence_request_id=evidence_request_id,
        caption=caption,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        idempotency_key=idempotency_key,
    )
    return asset, True


async def create_invoice_intent(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    job_id: uuid.UUID | None = None,
    caption: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    size_bytes: int | None = None,
    idempotency_key: str | None = None,
) -> tuple[EvidenceAsset, bool]:
    """Owner-only invoice document; ``job_id`` (optional) must be the caller's own job.
    A standalone invoice (no job) confers no contractor access or feedback eligibility."""
    job = None
    if job_id is not None:
        job = (await access.job_for(db, user_id, job_id, owner_only=True, lock=True)).job
    replay = await _replay(db, user_id, user_id, idempotency_key, purpose="invoice", job_id=job_id)
    if replay is not None:
        return replay, False
    asset = await _new_intent(
        db,
        owner_id=user_id,
        job=job,
        uploaded_by=user_id,
        organization_id=None,
        purpose="invoice",
        evidence_request_id=None,
        caption=caption,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        idempotency_key=idempotency_key,
    )
    return asset, True


# --------------------------------------------------------------------------- authorization
@dataclass
class AssetAccess:
    asset: EvidenceAsset
    role: str  # "owner" | "contractor"
    actor: access.JobActor | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


async def resolve(db: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID, *, lock_job: bool = False) -> AssetAccess:
    """Current access to one asset (re-evaluated on every request, D23).

    Invoice documents: their owner only. Job media: like the job's ``evidence`` section —
    the owner sees every non-deleted asset; an assigned contractor sees available assets
    and their own uploads. Everyone else: 404 (no existence leak)."""
    asset = await db.get(EvidenceAsset, asset_id, populate_existing=True)
    if asset is None or asset.status == "deleted":
        raise not_found("Asset")
    if asset.purpose == "invoice" or asset.job_id is None:
        if asset.owner_id != user_id:
            raise not_found("Asset")
        if asset.job_id is not None and lock_job:
            await access.job_for(db, user_id, asset.job_id, owner_only=True, lock=True)
        return AssetAccess(asset, "owner")
    actor = await access.job_for(db, user_id, asset.job_id, section="evidence", lock=lock_job)
    if not actor.is_owner and asset.status != "available" and asset.uploaded_by != user_id:
        raise not_found("Asset")
    return AssetAccess(asset, actor.role, actor)


async def get_invoice_asset(
    db: AsyncSession, owner_id: uuid.UUID, asset_id: uuid.UUID, *, require_available: bool = True
) -> EvidenceAsset:
    """For the invoices workstream: the caller's own invoice document (404 otherwise)."""
    asset = await db.get(EvidenceAsset, asset_id, populate_existing=True)
    if asset is None or asset.purpose != "invoice" or asset.owner_id != owner_id or asset.status == "deleted":
        raise not_found("Invoice document")
    if require_available and asset.status != "available":
        raise AppError(409, "asset_not_available", "The document is still being checked or was rejected")
    return asset


def signed_download(asset: EvidenceAsset, variant: str = "derivative") -> tuple[str, datetime]:
    """A short-lived URL for an *already authorised* available asset."""
    if asset.status != "available" or asset.deleted_at is not None:
        raise AppError(409, "asset_not_available", "This file is not available for download")
    settings = get_settings()
    seconds = max(1, min(settings.signed_url_seconds, storage.MAX_SIGNED_URL_SECONDS))
    if variant == "original":
        key, media_type = asset.storage_key, asset.detected_type or "application/octet-stream"
    else:
        key, media_type = asset.derivative_key, derivative_media_type(asset)
    if not key:
        raise AppError(409, "asset_not_available", "This file is not available for download")
    expires_at = utcnow() + timedelta(seconds=seconds)
    try:
        url = storage.get_store().signed_get_url(
            key, filename=download_filename(asset, variant), content_type=media_type, seconds=seconds
        )
    except storage.ObjectStoreError:
        raise AppError(503, "storage_unavailable", "File storage is temporarily unavailable") from None
    return url, expires_at


async def download_url(db: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID, variant: str) -> tuple[str, datetime]:
    """Authorise (again, on every request) and sign. Originals: owner only, audited."""
    if variant not in ("derivative", "original"):
        raise AppError(422, "invalid_variant", "variant must be derivative or original")
    resolved = await resolve(db, user_id, asset_id)
    asset = resolved.asset
    if asset.status != "available":
        raise AppError(409, "asset_not_available", "This file is not available for download")
    if variant == "original":
        if not resolved.is_owner:
            raise AppError(403, "owner_only", "Only the owner can download the original file")
        await audit.record(
            db, user_id, "service_asset_original_download", "service_asset", asset.id, {"job_id": str(asset.job_id)}
        )
    return signed_download(asset, variant)


async def derivative_bytes(db: AsyncSession, asset: EvidenceAsset) -> bytes:
    """Bytes of the metadata-free derivative for analysis providers — never the original,
    never EXIF/metadata. Re-reads the asset first; call with no row locks held (the
    storage read happens after the check). Media type: :func:`derivative_media_type`."""
    fresh = await db.get(EvidenceAsset, asset.id, populate_existing=True)
    if fresh is None or fresh.status != "available" or fresh.deleted_at is not None or not fresh.derivative_key:
        raise AppError(409, "asset_not_available", "This file is not available")
    try:
        return await asyncio.to_thread(storage.get_store().get, fresh.derivative_key)
    except storage.ObjectStoreError:
        raise AppError(503, "storage_unavailable", "File storage is temporarily unavailable") from None


# --------------------------------------------------------------------------- content receipt
@dataclass
class Receipt:
    asset_id: uuid.UUID
    max_bytes: int
    token: uuid.UUID | None  # None: content was already received (idempotent replay check)
    storage_key: str | None = None
    sha256: str | None = None


async def begin_receive(
    db: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID, content_length: int | None
) -> Receipt:
    """Check the uploader's current authority and claim the intent for this request. Commits
    (no transaction stays open while the body streams)."""
    asset = await db.get(EvidenceAsset, asset_id, populate_existing=True)
    if asset is None or asset.uploaded_by != user_id or asset.status == "deleted":
        raise not_found("Upload")
    if asset.job_id is not None:
        if asset.purpose == "invoice":
            await access.job_for(db, user_id, asset.job_id, owner_only=True)
        else:
            await access.job_for(db, user_id, asset.job_id, section="evidence")
    if asset.status != "upload_pending":
        receipt = Receipt(asset.id, asset.max_bytes, None, sha256=asset.sha256)
        await db.commit()
        return receipt
    now = utcnow()
    if asset.upload_expires_at is not None and asset.upload_expires_at < now:
        raise AppError(410, "upload_intent_expired", "This upload link has expired; start the upload again")
    if content_length is not None and content_length > asset.max_bytes:
        raise AppError(413, "file_too_large", "The file is larger than allowed", extra={"max_bytes": asset.max_bytes})
    token = uuid.uuid4()
    lease = timedelta(seconds=get_settings().service_processing_lease_seconds)
    claimed = (
        await db.execute(
            update(EvidenceAsset)
            .where(
                EvidenceAsset.id == asset.id,
                EvidenceAsset.status == "upload_pending",
                or_(EvidenceAsset.lease_token.is_(None), EvidenceAsset.lease_expires_at < now),
            )
            .values(lease_token=token, lease_expires_at=now + lease)
            .returning(EvidenceAsset.storage_key, EvidenceAsset.max_bytes)
            .execution_options(synchronize_session=False)
        )
    ).first()
    await db.commit()
    if claimed is None:
        raise AppError(409, "upload_in_progress", "This file is already being uploaded")
    return Receipt(asset.id, claimed.max_bytes, token, storage_key=claimed.storage_key)


async def read_body(stream: AsyncIterator[bytes], max_bytes: int) -> bytes:
    """Read a request body, refusing (413) as soon as it exceeds ``max_bytes``."""
    buf = bytearray()
    async for chunk in stream:
        if not chunk:
            continue
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise AppError(413, "file_too_large", "The file is larger than allowed", extra={"max_bytes": max_bytes})
    return bytes(buf)


async def abort_receive(db: AsyncSession, receipt: Receipt) -> None:
    await db.rollback()
    if receipt.token is None:
        return
    await db.execute(
        update(EvidenceAsset)
        .where(EvidenceAsset.id == receipt.asset_id, EvidenceAsset.lease_token == receipt.token)
        .values(lease_token=None, lease_expires_at=None)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def finish_receive(db: AsyncSession, receipt: Receipt, data: bytes) -> EvidenceAsset:
    """Store the bytes under the quarantine key (no transaction open), then mark the asset
    quarantined under job → asset locks if this request still holds the receipt. Commits
    and queues processing."""
    if not data:
        await abort_receive(db, receipt)
        raise AppError(422, "empty_upload", "The upload was empty")
    digest = hashlib.sha256(data).hexdigest()
    try:
        await asyncio.to_thread(storage.get_store().put, receipt.storage_key, data, "application/octet-stream")
    except storage.ObjectStoreError:
        await abort_receive(db, receipt)
        raise AppError(503, "storage_unavailable", "File storage is temporarily unavailable") from None
    head = await db.get(EvidenceAsset, receipt.asset_id, populate_existing=True)
    if head is not None and head.job_id is not None:
        await _lock_job(db, head.job_id)
    asset = await _lock_asset(db, receipt.asset_id)
    if asset is None or asset.lease_token != receipt.token or asset.status != "upload_pending":
        await db.rollback()
        raise AppError(409, "upload_in_progress", "This file is already being uploaded")
    asset.status = "quarantined"
    asset.size_bytes = len(data)
    asset.sha256 = digest
    asset.lease_token = None
    asset.lease_expires_at = None
    asset.scan_result = {"status": "pending"}
    asset.version += 1
    await db.commit()
    enqueue_processing(asset.id)
    return asset


# --------------------------------------------------------------------------- detection and decoding
def detect_type(data: bytes) -> str | None:
    """Magic-byte detection; extension and client MIME type are never consulted."""
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return HEIC
    if data.startswith(b"%PDF-"):
        return PDF
    return None


class RejectedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Outcome:
    status: str  # "available" | "rejected" | "retry"
    reason: str | None = None
    scan: dict = field(default_factory=dict)
    detected_type: str | None = None
    width: int | None = None
    height: int | None = None
    pages: int | None = None
    quality: dict = field(default_factory=dict)
    derivative: bytes | None = None


def capture_quality(img: Image.Image) -> dict:
    """Advisory blur/darkness hints from simple statistics (no text is read or invented)."""
    gray = img.convert("L")
    gray.thumbnail((512, 512))
    mean = ImageStat.Stat(gray).mean[0]
    result = {
        "darkness": "dark" if mean < DARK_MEAN_THRESHOLD else "ok",
        "mean_luminance": round(mean, 1),
        "framing": "not_assessed",
        "label_legibility": "not_assessed",
        "method": "heuristic-v1",
    }
    if min(gray.size) < 32:
        result.update(blur="not_assessed", blur_score=None)
        return result
    laplacian = gray.filter(ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128))
    variance = ImageStat.Stat(laplacian).var[0]
    result.update(blur="blurry" if variance < BLUR_VARIANCE_THRESHOLD else "ok", blur_score=round(variance, 1))
    return result


def perceptual_hash(img: Image.Image) -> str:
    """64-bit difference hash (dHash) of the oriented image."""
    small = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = small.load()
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _flatten(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def process_image(data: bytes, detected: str) -> Outcome:
    settings = get_settings()
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            img = Image.open(BytesIO(data))
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise RejectedError("too_many_pixels") from None
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
            raise RejectedError("malformed_image") from None
        if img.format != _PIL_FORMAT[detected]:
            raise RejectedError("malformed_image")
        width, height = img.size
        if width <= 0 or height <= 0:
            raise RejectedError("malformed_image")
        if width * height > settings.service_image_max_pixels:
            raise RejectedError("too_many_pixels")
        try:
            img.load()
            try:
                oriented = ImageOps.exif_transpose(img)
            except Exception:  # a corrupt orientation tag must not block an otherwise valid image
                oriented = img
            rgb = _flatten(oriented)
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise RejectedError("too_many_pixels") from None
        except (OSError, ValueError, SyntaxError, EOFError, MemoryError):
            raise RejectedError("malformed_image") from None
    if max(rgb.size) > DERIVATIVE_MAX_EDGE:
        rgb.thumbnail((DERIVATIVE_MAX_EDGE, DERIVATIVE_MAX_EDGE), Image.Resampling.LANCZOS)
    out = BytesIO()
    # No exif=/icc_profile=/xmp= arguments: the derivative carries pixels only.
    rgb.save(out, "JPEG", quality=85, optimize=True)
    quality = capture_quality(rgb)
    quality["phash"] = perceptual_hash(rgb)
    return Outcome(
        "available",
        detected_type=detected,
        width=rgb.size[0],
        height=rgb.size[1],
        quality=quality,
        derivative=out.getvalue(),
    )


# Names whose presence makes a PDF active (scripts, auto-actions, launchers, attachments,
# forms that submit or run scripts, rich media).
_PDF_ACTIVE_NAMES = (
    "JavaScript",
    "JS",
    "OpenAction",
    "AA",
    "Launch",
    "EmbeddedFile",
    "EmbeddedFiles",
    "XFA",
    "RichMedia",
    "SubmitForm",
    "ImportData",
    "GoToE",
)
_PDF_ACTIVE_RAW = re.compile(rb"/(?:" + b"|".join(n.encode() for n in _PDF_ACTIVE_NAMES) + rb")(?=[\s/<>\[\]()%{}]|$)")
_PDF_ACTIVE_KEYS = frozenset("/" + n for n in _PDF_ACTIVE_NAMES)
_PDF_ACTIVE_VALUES = frozenset({"/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/GoToE", "/RichMediaExecute"})
_PDF_ACTIVE_SUBTYPES = frozenset({"/FileAttachment", "/RichMedia", "/Movie", "/Sound", "/Screen", "/3D"})


def _walk_pdf(root) -> None:
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

    seen: set[tuple[int, int]] = set()
    stack = [root]
    visited = 0
    while stack:
        node = stack.pop()
        if isinstance(node, IndirectObject):
            ref = (node.idnum, node.generation)
            if ref in seen:
                continue
            seen.add(ref)
            node = node.get_object()
        visited += 1
        if visited > PDF_MAX_OBJECTS:
            raise RejectedError("malformed_pdf")
        if isinstance(node, DictionaryObject):
            for key, value in node.items():
                if key in _PDF_ACTIVE_KEYS:
                    raise RejectedError("active_pdf_content")
                if key in ("/S", "/Subtype", "/Type") and isinstance(value, NameObject):
                    if value in _PDF_ACTIVE_VALUES or (key == "/Subtype" and value in _PDF_ACTIVE_SUBTYPES):
                        raise RejectedError("active_pdf_content")
                    if key == "/Type" and value in ("/EmbeddedFile", "/Filespec") and "/EF" in node:
                        raise RejectedError("active_pdf_content")
                if key == "/EF":
                    raise RejectedError("active_pdf_content")
                stack.append(value)
        elif isinstance(node, ArrayObject):
            stack.extend(node)


def process_pdf(data: bytes) -> Outcome:
    """Inert validation; the derivative is the pages re-written without document metadata."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    settings = get_settings()
    if _PDF_ACTIVE_RAW.search(data):
        raise RejectedError("active_pdf_content")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted or "/Encrypt" in reader.trailer:
                raise RejectedError("encrypted_pdf")
            pages = len(reader.pages)
            if pages <= 0:
                raise RejectedError("malformed_pdf")
            if pages > settings.service_pdf_max_pages:
                raise RejectedError("too_many_pages")
            _walk_pdf(reader.trailer)
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            for page in writer.pages:
                for key in ("/Metadata", "/PieceInfo"):
                    if key in page:
                        del page[NameObject(key)]
            writer.metadata = None
            out = BytesIO()
            writer.write(out)
    except RejectedError:
        raise
    except RecursionError:
        raise RejectedError("malformed_pdf") from None
    except Exception:  # pypdf raises many types for malformed input; all mean "not inert/valid"
        raise RejectedError("malformed_pdf") from None
    derivative = out.getvalue()
    if _PDF_ACTIVE_RAW.search(derivative):
        raise RejectedError("active_pdf_content")
    return Outcome("available", detected_type=PDF, pages=pages, quality={"method": "pdf"}, derivative=derivative)


def analyse(data: bytes, purpose: str, expected_sha256: str | None) -> Outcome:
    """Pure CPU/scanner work for one asset — runs with no database transaction open."""
    if expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256:
        return Outcome("rejected", reason="integrity_mismatch")
    result = scanner.scan(data)
    scan = result.as_dict()
    if result.status == "infected":
        return Outcome("rejected", reason="malware_detected", scan=scan)
    if result.status != "clean":
        return Outcome("retry", reason="scanner_unavailable", scan=scan)
    detected = detect_type(data)
    if detected is None:
        return Outcome("rejected", reason="unsupported_type", scan=scan)
    if detected not in PURPOSE_TYPES.get(purpose, frozenset()):
        return Outcome("rejected", reason="type_not_allowed", scan=scan, detected_type=detected)
    if len(data) > type_max_bytes(detected):
        return Outcome("rejected", reason="too_large", scan=scan, detected_type=detected)
    try:
        outcome = process_pdf(data) if detected == PDF else process_image(data, detected)
    except RejectedError as exc:
        return Outcome("rejected", reason=exc.code, scan=scan, detected_type=detected)
    outcome.scan = scan
    return outcome


# --------------------------------------------------------------------------- processing (claim → work → publish)
@dataclass
class Claim:
    asset_id: uuid.UUID
    token: uuid.UUID
    storage_key: str
    purpose: str
    sha256: str | None
    job_id: uuid.UUID | None


async def claim(db: AsyncSession, asset_id: uuid.UUID) -> Claim | None:
    """Claim a quarantined (or lease-expired processing) asset. Short UPDATE … RETURNING; commits."""
    settings = get_settings()
    now = utcnow()
    token = uuid.uuid4()
    row = (
        await db.execute(
            update(EvidenceAsset)
            .where(
                EvidenceAsset.id == asset_id,
                EvidenceAsset.deleted_at.is_(None),
                EvidenceAsset.attempts < settings.service_processing_max_attempts,
                or_(
                    and_(
                        EvidenceAsset.status == "quarantined",
                        or_(EvidenceAsset.lease_token.is_(None), EvidenceAsset.lease_expires_at < now),
                    ),
                    and_(EvidenceAsset.status == "processing", EvidenceAsset.lease_expires_at < now),
                ),
            )
            .values(
                status="processing",
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=settings.service_processing_lease_seconds),
                attempts=EvidenceAsset.attempts + 1,
            )
            .returning(EvidenceAsset.storage_key, EvidenceAsset.purpose, EvidenceAsset.sha256, EvidenceAsset.job_id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    await db.commit()
    if row is None:
        return None
    return Claim(asset_id, token, row.storage_key, row.purpose, row.sha256, row.job_id)


async def _locked_for(db: AsyncSession, c: Claim) -> tuple[ServiceJob | None, EvidenceAsset | None]:
    job = await _lock_job(db, c.job_id) if c.job_id else None
    asset = await _lock_asset(db, c.asset_id)
    if asset is None or asset.lease_token != c.token or asset.status != "processing" or asset.deleted_at is not None:
        await db.rollback()
        return job, None
    return job, asset


async def release_for_retry(db: AsyncSession, c: Claim, scan: dict) -> str:
    """Scanner/storage failure: back to quarantined (never available). Commits."""
    _, asset = await _locked_for(db, c)
    if asset is None:
        return "lease_lost"
    asset.status = "quarantined"
    asset.scan_result = scan or {"status": "error"}
    asset.lease_token = None
    asset.lease_expires_at = None
    await db.commit()
    return "quarantined"


async def publish_rejection(db: AsyncSession, c: Claim, outcome: Outcome) -> str:
    _, asset = await _locked_for(db, c)
    if asset is None:
        return "lease_lost"
    asset.status = "rejected"
    asset.rejection_reason = outcome.reason
    asset.scan_result = outcome.scan
    asset.detected_type = outcome.detected_type
    asset.lease_token = None
    asset.lease_expires_at = None
    asset.version += 1
    await db.commit()
    return "rejected"


async def _duplicate_of(db: AsyncSession, asset: EvidenceAsset, phash: str | None) -> uuid.UUID | None:
    if asset.job_id is None:
        return None
    base = select(EvidenceAsset.id, EvidenceAsset.quality).where(
        EvidenceAsset.job_id == asset.job_id,
        EvidenceAsset.id != asset.id,
        EvidenceAsset.status == "available",
        EvidenceAsset.deleted_at.is_(None),
    )
    same = (
        await db.execute(base.where(EvidenceAsset.sha256 == asset.sha256).order_by(EvidenceAsset.created_at).limit(1))
    ).first()
    if same is not None:
        return same.id
    if not phash:
        return None
    rows = (
        await db.execute(base.where(EvidenceAsset.quality["phash"].is_not(None)).order_by(EvidenceAsset.created_at))
    ).all()
    for row in rows:
        other = (row.quality or {}).get("phash")
        if other and hamming(other, phash) <= PHASH_MAX_DISTANCE:
            return row.id
    return None


async def publish_available(
    db: AsyncSession, c: Claim, outcome: Outcome, original_key: str, derivative_key: str
) -> str:
    """Make the asset available if this worker still holds the lease. Commits."""
    job, asset = await _locked_for(db, c)
    if asset is None:
        return "lease_lost"
    if job is not None and job.deleted_at is not None:
        await db.rollback()
        return "lease_lost"
    now = utcnow()
    asset.status = "available"
    asset.storage_key = original_key
    asset.derivative_key = derivative_key
    asset.detected_type = outcome.detected_type
    asset.width, asset.height, asset.pages = outcome.width, outcome.height, outcome.pages
    asset.quality = outcome.quality
    asset.scan_result = outcome.scan
    asset.rejection_reason = None
    asset.duplicate_of_id = await _duplicate_of(db, asset, outcome.quality.get("phash"))
    asset.lease_token = None
    asset.lease_expires_at = None
    asset.version += 1
    if job is not None:
        await revisions.bump(db, job, reason="asset_available")
    if asset.evidence_request_id is not None and job is not None:
        request = (
            await db.execute(
                select(EvidenceRequest)
                .where(EvidenceRequest.id == asset.evidence_request_id, EvidenceRequest.job_id == job.id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if request is not None and request.status == "outstanding":
            request.status = "answered"
            request.answered_by = asset.uploaded_by
            request.answered_at = now
            request.version += 1
            if request.requested_by is not None and request.requested_by != asset.uploaded_by:
                await notify(
                    db, request.requested_by, "evidence_answered", job_id=job.id, key=f"{request.id}:{asset.id}"
                )
    await db.commit()
    return "available"


async def process_asset(db: AsyncSession, asset_id: uuid.UUID) -> str:
    """Claim → fetch/scan/decode/derive outside any transaction → publish under locks."""
    c = await claim(db, asset_id)
    if c is None:
        return "not_claimed"
    store = storage.get_store()
    try:
        data = await asyncio.to_thread(store.get, c.storage_key)
    except storage.ObjectStoreError:
        return await release_for_retry(db, c, {"status": "error", "detail": "storage_unavailable"})
    outcome = await asyncio.to_thread(analyse, data, c.purpose, c.sha256)
    if outcome.status == "retry":
        return await release_for_retry(db, c, outcome.scan)
    if outcome.status == "rejected":
        result = await publish_rejection(db, c, outcome)
        if result == "rejected":
            await _quiet_delete(c.storage_key)
        return result
    original_key, derivative_key = storage.new_key("original"), storage.new_key("derived")
    try:
        await asyncio.to_thread(store.put, original_key, data, outcome.detected_type or "application/octet-stream")
        await asyncio.to_thread(store.put, derivative_key, outcome.derivative, derivative_media_type_for(outcome))
    except storage.ObjectStoreError:
        await _quiet_delete(original_key, derivative_key)
        return await release_for_retry(db, c, {**outcome.scan, "detail": "storage_unavailable"})
    result = await publish_available(db, c, outcome, original_key, derivative_key)
    if result == "available":
        await _quiet_delete(c.storage_key)
    else:
        await _quiet_delete(original_key, derivative_key)  # stale worker: discard its output
    return result


def derivative_media_type_for(outcome: Outcome) -> str:
    return PDF if outcome.detected_type == PDF else JPEG


async def _quiet_delete(*keys: str) -> None:
    store = storage.get_store()
    for key in keys:
        try:
            await asyncio.to_thread(store.delete, key)
        except storage.ObjectStoreError:
            logger.warning("Could not delete a superseded object")


# --------------------------------------------------------------------------- deletion
async def delete_asset(
    db: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID, expected_version: int | None = None
) -> list[str]:
    """Job owner (or invoice owner); or the uploader while the asset is not yet available
    to anyone else. Locks job → asset; bumps the evidence revision when an available asset
    goes (dependent analysis/briefs become stale). Returns the keys to purge after commit."""
    resolved = await resolve(db, user_id, asset_id, lock_job=True)
    if not resolved.is_owner and (resolved.asset.uploaded_by != user_id or resolved.asset.status == "available"):
        raise AppError(403, "owner_only", "Only the job owner can delete a shared file")
    asset = await _lock_asset(db, asset_id)
    if asset is None or asset.status == "deleted":
        return []
    access.check_version(asset.version, expected_version, "file")
    in_use = (
        await db.execute(select(InvoiceRevision.id).where(InvoiceRevision.source_asset_id == asset.id).limit(1))
    ).first()
    if in_use is not None:
        raise AppError(409, "asset_in_use", "This document belongs to an invoice; delete the invoice instead")
    was_available = asset.status == "available"
    keys = [k for k in (asset.storage_key, asset.derivative_key) if k]
    asset.status = "deleted"
    asset.deleted_at = utcnow()
    asset.lease_token = None
    asset.lease_expires_at = None
    asset.version += 1
    job = resolved.actor.job if resolved.actor is not None else None
    if was_available and job is not None:
        await revisions.bump(db, job, reason="asset_deleted")
        await _reopen_request(db, asset)
    await audit.record(
        db,
        user_id,
        "service_asset_deleted",
        "service_asset",
        asset.id,
        {"job_id": str(asset.job_id) if asset.job_id else None, "was_available": was_available, "role": resolved.role},
    )
    await db.flush()
    return keys


async def _reopen_request(db: AsyncSession, asset: EvidenceAsset) -> None:
    if asset.evidence_request_id is None:
        return
    request = (
        await db.execute(
            select(EvidenceRequest)
            .where(EvidenceRequest.id == asset.evidence_request_id, EvidenceRequest.job_id == asset.job_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None or request.status != "answered" or request.answer_note:
        return
    other = (
        await db.execute(
            select(EvidenceAsset.id).where(
                EvidenceAsset.evidence_request_id == request.id,
                EvidenceAsset.id != asset.id,
                EvidenceAsset.status == "available",
            )
        )
    ).first()
    if other is None:
        request.status = "outstanding"
        request.answered_by = None
        request.answered_at = None
        request.version += 1


async def mark_job_assets_deleted(db: AsyncSession, job_id: uuid.UUID) -> list[uuid.UUID]:
    """For job deletion (caller holds the job lock): every asset of the job becomes
    ``deleted``; the objects are purged by :func:`sweep_deleted_objects`."""
    rows = (
        await db.execute(
            update(EvidenceAsset)
            .where(EvidenceAsset.job_id == job_id, EvidenceAsset.status != "deleted")
            .values(status="deleted", deleted_at=utcnow(), lease_token=None, lease_expires_at=None)
            .returning(EvidenceAsset.id)
            .execution_options(synchronize_session=False)
        )
    ).all()
    return [r.id for r in rows]


# --------------------------------------------------------------------------- retention / recovery sweeps
async def sweep_abandoned_intents(db: AsyncSession, limit: int = 500) -> int:
    """Remove upload intents past their expiry (default 24 h) and any bytes they left."""
    now = utcnow()
    stale = (EvidenceAsset.status == "upload_pending") & (EvidenceAsset.upload_expires_at < now)
    idle = or_(EvidenceAsset.lease_token.is_(None), EvidenceAsset.lease_expires_at < now)
    rows = (await db.execute(select(EvidenceAsset.id, EvidenceAsset.storage_key).where(stale, idle).limit(limit))).all()
    await db.commit()
    if not rows:
        return 0
    removable = []
    store = storage.get_store()
    for row in rows:
        try:
            await asyncio.to_thread(store.delete, row.storage_key)
            removable.append(row.id)
        except storage.ObjectStoreError:
            logger.warning("Abandoned upload object deletion deferred")
    if removable:
        await db.execute(
            delete(EvidenceAsset)
            .where(EvidenceAsset.id.in_(removable), stale, idle)
            .execution_options(synchronize_session=False)
        )
    await db.commit()
    return len(removable)


async def sweep_deleted_objects(db: AsyncSession, limit: int = 500) -> int:
    """Retry object deletion for deleted assets whose keys are not yet tombstoned."""
    rows = (
        await db.execute(
            select(EvidenceAsset.id, EvidenceAsset.storage_key, EvidenceAsset.derivative_key)
            .where(EvidenceAsset.status == "deleted", ~EvidenceAsset.storage_key.startswith(TOMBSTONE_PREFIX))
            .limit(limit)
        )
    ).all()
    await db.commit()
    done = 0
    for row in rows:
        if await purge_objects(db, row.id, [row.storage_key, row.derivative_key]):
            done += 1
    return done


async def recoverable_assets(db: AsyncSession, limit: int = 200, min_age_seconds: int = 120) -> list[uuid.UUID]:
    """Quarantined assets never processed (broker outage, scanner failure with attempts
    left) and processing assets whose worker lease expired (crash)."""
    settings = get_settings()
    now = utcnow()
    rows = (
        await db.execute(
            select(EvidenceAsset.id)
            .where(
                EvidenceAsset.deleted_at.is_(None),
                EvidenceAsset.attempts < settings.service_processing_max_attempts,
                or_(
                    and_(
                        EvidenceAsset.status == "quarantined",
                        EvidenceAsset.lease_token.is_(None),
                        EvidenceAsset.updated_at < now - timedelta(seconds=min_age_seconds),
                    ),
                    and_(EvidenceAsset.status == "processing", EvidenceAsset.lease_expires_at < now),
                ),
            )
            .order_by(EvidenceAsset.updated_at)
            .limit(limit)
        )
    ).all()
    await db.commit()
    return [r.id for r in rows]


def _draft_candidates(cutoff: datetime):
    return (
        (ServiceJob.status == "draft")
        & ServiceJob.deleted_at.is_(None)
        & ServiceJob.retention_hold.is_(False)
        & (ServiceJob.updated_at < cutoff)
        & ~exists().where(JobAssignment.job_id == ServiceJob.id)
        & ~exists().where(ModerationCase.job_id == ServiceJob.id, ModerationCase.status.in_(("open", "under_review")))
        & ~exists().where(Invoice.job_id == ServiceJob.id)
    )


async def sweep_inactive_drafts(db: AsyncSession, limit: int = 100) -> dict:
    """Never-assigned drafts inactive for ``service_draft_retention_days``: first a recorded
    advance notice (audit; no content-free notification kind exists for it yet), then —
    on a sweep at least ``RETENTION_NOTICE_DAYS`` later with no activity since — deletion.
    Jobs with a retention hold, an open moderation case or a linked invoice are never
    deleted."""
    settings = get_settings()
    now = utcnow()
    cutoff = now - timedelta(days=settings.service_draft_retention_days)
    ids = (await db.execute(select(ServiceJob.id).where(_draft_candidates(cutoff)).limit(limit))).scalars().all()
    await db.commit()
    noticed = deleted = 0
    deleted_jobs: list[uuid.UUID] = []
    for job_id in ids:
        job = (
            await db.execute(
                select(ServiceJob)
                .where(ServiceJob.id == job_id, _draft_candidates(cutoff))
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if job is None:
            await db.rollback()
            continue
        notice = (
            await db.execute(
                select(AuditLog.created_at)
                .where(AuditLog.action == "service_job_retention_notice", AuditLog.entity_id == str(job.id))
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if notice is None or notice < job.updated_at:
            await audit.record(
                db,
                None,
                "service_job_retention_notice",
                "service_job",
                job.id,
                {"owner_id": str(job.owner_id), "delete_after_days": RETENTION_NOTICE_DAYS},
            )
            noticed += 1
        elif notice <= now - timedelta(days=RETENTION_NOTICE_DAYS):
            job.deleted_at = now
            await mark_job_assets_deleted(db, job.id)
            await audit.record(
                db, None, "service_job_retention_deleted", "service_job", job.id, {"owner_id": str(job.owner_id)}
            )
            deleted += 1
            deleted_jobs.append(job.id)
        await db.commit()
    if deleted_jobs:
        await sweep_deleted_objects(db)
        remaining = select(EvidenceAsset.id).where(
            EvidenceAsset.job_id == ServiceJob.id, ~EvidenceAsset.storage_key.startswith(TOMBSTONE_PREFIX)
        )
        await db.execute(
            delete(ServiceJob)
            .where(ServiceJob.id.in_(deleted_jobs), ServiceJob.deleted_at.is_not(None), ~remaining.exists())
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    return {"noticed": noticed, "deleted": deleted}
