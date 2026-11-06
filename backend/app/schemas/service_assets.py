"""Private evidence/invoice media contracts. Storage keys and paths are never exposed."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import APIModel, StrictInput

# Capture-quality keys returned to clients (internal fingerprints such as the perceptual
# hash stay server-side).
PUBLIC_QUALITY_KEYS = ("blur", "blur_score", "darkness", "mean_luminance", "framing", "label_legibility", "method")


class _IntentBase(StrictInput):
    caption: str | None = Field(default=None, max_length=500)
    # Declared by the client for display only; content is validated independently.
    filename: str | None = Field(default=None, max_length=200)
    content_type: str | None = Field(default=None, max_length=100)
    # Optional declared size: the intent then reserves (and enforces) this many bytes.
    size_bytes: int | None = Field(default=None, gt=0)


class JobAssetIntentCreate(_IntentBase):
    purpose: Literal["job_photo", "job_document"] = "job_photo"
    evidence_request_id: uuid.UUID | None = None


class InvoiceAssetIntentCreate(_IntentBase):
    job_id: uuid.UUID | None = None


class DownloadUrlRequest(StrictInput):
    variant: Literal["derivative", "original"] = "derivative"


class AssetResponse(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID | None
    purpose: str
    status: str
    uploaded_by_role: str
    uploaded_by_me: bool
    evidence_request_id: uuid.UUID | None
    caption: str | None
    detected_type: str | None
    size_bytes: int | None
    max_bytes: int
    width: int | None
    height: int | None
    pages: int | None
    quality: dict
    duplicate_of_id: uuid.UUID | None
    rejection_reason: str | None
    upload_expires_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime

    @field_validator("quality", mode="before")
    @classmethod
    def _public_quality(cls, value):
        return {k: v for k, v in (value or {}).items() if k in PUBLIC_QUALITY_KEYS}


class UploadInstruction(APIModel):
    method: Literal["PUT"] = "PUT"
    url: str
    max_bytes: int
    expires_at: datetime | None


class AssetIntentResponse(APIModel):
    asset: AssetResponse
    upload: UploadInstruction | None  # None once content has been received


class AssetList(APIModel):
    items: list[AssetResponse]
    total: int


class DownloadUrlResponse(APIModel):
    url: str
    expires_at: datetime
    variant: str
    # Inline rendering is never offered; PDFs and images download as attachments.
    disposition: Literal["attachment"] = "attachment"
