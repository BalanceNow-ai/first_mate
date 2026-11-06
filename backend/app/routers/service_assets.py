"""Private evidence/invoice media: upload intents, content, status, signed downloads, deletion (workstream A1).

Authority (re-evaluated on every request, D23):

* job media — the job owner, or the assigned contractor holding the ``evidence`` section
  (``access.job_for``); contractors see only available assets (plus their own uploads);
* invoice documents — their owner only; a linked job must be the caller's own job;
* originals — the owner only, on request, audited; everyone else gets the
  metadata-stripped derivative;
* content upload — only the uploader, only while the intent is pending and unexpired.

Signed URLs last at most ``SIGNED_URL_SECONDS`` (≤ 300 s); storage keys never appear in
responses. No database transaction is open while a body streams or storage is called.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.core.rate_limit import mutation_limit, rate_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.service_jobs import EvidenceAsset
from app.schemas.service_assets import (
    AssetIntentResponse,
    AssetList,
    AssetResponse,
    DownloadUrlRequest,
    DownloadUrlResponse,
    InvoiceAssetIntentCreate,
    JobAssetIntentCreate,
    UploadInstruction,
)
from app.services.service_jobs import access, media, storage
from app.services.service_jobs.storage_s3 import safe_filename

router = APIRouter(prefix="", tags=["Service evidence"])

LOCAL_DOWNLOAD_TYPES = frozenset({media.JPEG, media.PNG, media.WEBP, media.HEIC, media.PDF})


def asset_out(asset: EvidenceAsset, user_id: uuid.UUID) -> AssetResponse:
    data = {c: getattr(asset, c) for c in AssetResponse.model_fields if hasattr(asset, c)}
    data["uploaded_by_role"] = "contractor" if asset.uploader_organization_id else "owner"
    data["uploaded_by_me"] = asset.uploaded_by == user_id
    return AssetResponse.model_validate(data)


def _intent_out(asset: EvidenceAsset, user_id: uuid.UUID) -> AssetIntentResponse:
    upload = None
    if asset.status == "upload_pending":
        upload = UploadInstruction(
            url=f"{get_settings().api_v1_prefix}/service-assets/{asset.id}/content",
            max_bytes=asset.max_bytes,
            expires_at=asset.upload_expires_at,
        )
    return AssetIntentResponse(asset=asset_out(asset, user_id), upload=upload)


def _content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise AppError(400, "invalid_content_length", "Invalid Content-Length") from None
    if value < 0:
        raise AppError(400, "invalid_content_length", "Invalid Content-Length")
    return value


# --- intents --------------------------------------------------------------------------
@router.post(
    "/service-jobs/{job_id}/assets/intents",
    response_model=AssetIntentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def create_job_asset_intent(
    job_id: uuid.UUID,
    body: JobAssetIntentCreate,
    user_id: CurrentUserId,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> AssetIntentResponse:
    """Start a photo/document upload for a job (owner, or assigned contractor with evidence)."""
    asset, created = await media.create_job_intent(
        db,
        user_id,
        job_id,
        purpose=body.purpose,
        evidence_request_id=body.evidence_request_id,
        caption=body.caption,
        filename=body.filename,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        idempotency_key=media.check_idempotency_key(idempotency_key),
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return _intent_out(asset, user_id)


@router.post(
    "/service-assets/invoice-intents",
    response_model=AssetIntentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def create_invoice_asset_intent(
    body: InvoiceAssetIntentCreate,
    user_id: CurrentUserId,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> AssetIntentResponse:
    """Start an invoice document upload (owner only; optional link to the caller's own job)."""
    asset, created = await media.create_invoice_intent(
        db,
        user_id,
        job_id=body.job_id,
        caption=body.caption,
        filename=body.filename,
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        idempotency_key=media.check_idempotency_key(idempotency_key),
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return _intent_out(asset, user_id)


# --- content ----------------------------------------------------------------------------
@router.put(
    "/service-assets/{asset_id}/content",
    response_model=AssetResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(mutation_limit())],
)
async def put_asset_content(
    asset_id: uuid.UUID,
    request: Request,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> AssetResponse:
    """Upload the raw bytes (any Content-Type; the content itself is checked). Repeating
    the same bytes is a no-op; different bytes after a completed upload are refused."""
    receipt = await media.begin_receive(db, user_id, asset_id, _content_length(request))
    try:
        data = await media.read_body(request.stream(), receipt.max_bytes)
    except (AppError, ClientDisconnect):
        await media.abort_receive(db, receipt)
        raise
    if receipt.token is None:
        if data and hashlib.sha256(data).hexdigest() == receipt.sha256:
            resolved = await media.resolve(db, user_id, asset_id)
            return asset_out(resolved.asset, user_id)
        raise AppError(409, "already_uploaded", "Content for this upload was already received")
    asset = await media.finish_receive(db, receipt, data)
    return asset_out(asset, user_id)


# --- local_fs signed downloads (development/test backend only) ----------------------------
@router.get("/service-assets/local-download", dependencies=[Depends(rate_limit("asset_download", 120))])
async def local_download(
    k: str = Query(max_length=200),
    e: int = Query(),
    n: str = Query(max_length=200),
    c: str = Query(max_length=100),
    t: str = Query(max_length=128),
) -> Response:
    """Serve a ``local_fs`` signed URL: HMAC + expiry checked, always as an attachment."""
    if get_settings().object_store_backend != "local_fs":
        raise not_found("Download")
    if c not in LOCAL_DOWNLOAD_TYPES or not storage.verify_local(k, e, n, c, t):
        raise AppError(403, "invalid_or_expired_link", "This download link is invalid or has expired")
    try:
        data = await asyncio.to_thread(storage.get_store().get, k)
    except storage.ObjectStoreError:
        raise not_found("Download") from None
    return Response(
        content=data,
        media_type=c,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename(n)}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


# --- status / listing ---------------------------------------------------------------------
@router.get("/service-assets/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> AssetResponse:
    """Status, capture-quality hints and safe metadata (authorised like its job/invoice)."""
    resolved = await media.resolve(db, user_id, asset_id)
    return asset_out(resolved.asset, user_id)


@router.get("/service-jobs/{job_id}/assets", response_model=AssetList)
async def list_job_assets(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> AssetList:
    """Job photos/documents. Contractors (with the evidence section) see available ones only."""
    actor = await access.job_for(db, user_id, job_id, section="evidence")
    q = select(EvidenceAsset).where(
        EvidenceAsset.job_id == job_id,
        EvidenceAsset.purpose.in_(media.JOB_PURPOSES),
        EvidenceAsset.status != "deleted",
    )
    if not actor.is_owner:
        q = q.where(EvidenceAsset.status == "available")
    if status_filter:
        q = q.where(EvidenceAsset.status == status_filter)
    rows = list((await db.execute(q.order_by(EvidenceAsset.created_at, EvidenceAsset.id))).scalars())
    vis = await access.visibility(db, actor)  # organization boundary; live updates off: the brief's files
    rows = [a for a in rows if vis.asset(a)]
    return AssetList(items=[asset_out(a, user_id) for a in rows[offset : offset + limit]], total=len(rows))


# --- downloads ----------------------------------------------------------------------------
@router.post(
    "/service-assets/{asset_id}/download-url",
    response_model=DownloadUrlResponse,
    dependencies=[Depends(mutation_limit())],
)
async def create_download_url(
    asset_id: uuid.UUID,
    user_id: CurrentUserId,
    body: DownloadUrlRequest | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> DownloadUrlResponse:
    """A short-lived (≤ 5 min) attachment URL. Derivative for everyone with access; the
    original only for the owner and only when asked for."""
    variant = body.variant if body else "derivative"
    url, expires_at = await media.download_url(db, user_id, asset_id, variant)
    return DownloadUrlResponse(url=url, expires_at=expires_at, variant=variant)


# --- deletion -----------------------------------------------------------------------------
@router.delete(
    "/service-assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(mutation_limit())],
)
async def delete_asset(
    asset_id: uuid.UUID,
    user_id: CurrentUserId,
    expected_version: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    """Delete a file: the job/invoice owner, or the uploader before it is shared. Objects
    are removed; dependent analysis/briefs become stale through the evidence revision."""
    keys = await media.delete_asset(db, user_id, asset_id, expected_version)
    await db.commit()
    if keys:
        await media.purge_objects(db, asset_id, keys)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
