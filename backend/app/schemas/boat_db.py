"""Boat OEM database and HIN decoding schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import APIModel, StrictInput

DataSource = Literal[
    "manufacturer",
    "dealer",
    "internal_curation",
    "crowdsourced_verified",
    "crowdsourced_unverified",
    "synthetic_fixture",
]


def _normalise_mics(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    out = []
    for code in v:
        code = code.strip().upper()
        if len(code) != 3 or not code.isalnum():
            raise ValueError("MIC codes are exactly 3 letters/digits")
        out.append(code)
    return sorted(set(out))


class EquipmentCategoryResponse(APIModel):
    id: uuid.UUID
    slug: str
    name: str
    parent_id: uuid.UUID | None


class EquipmentCategoryCreate(StrictInput):
    slug: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=100)
    parent_slug: str | None = None


class ManufacturerResponse(APIModel):
    id: uuid.UUID
    name: str
    country: str | None
    website: str | None
    mic_codes: list[str]
    is_synthetic: bool
    source: str | None
    model_count: int = 0


class ManufacturerCreate(StrictInput):
    name: str = Field(min_length=1, max_length=120)
    country: str | None = Field(None, max_length=60)
    website: str | None = Field(None, max_length=300)
    mic_codes: list[str] = []
    is_synthetic: bool = False
    source: str | None = Field(None, description="Attributable source for the record and any MIC codes")

    @field_validator("mic_codes")
    @classmethod
    def _mics(cls, v):
        return _normalise_mics(v)


class ManufacturerUpdate(StrictInput):
    name: str | None = Field(None, min_length=1, max_length=120)
    country: str | None = None
    website: str | None = None
    mic_codes: list[str] | None = None
    is_synthetic: bool | None = None
    source: str | None = None

    @field_validator("mic_codes")
    @classmethod
    def _mics(cls, v):
        return _normalise_mics(v)


class BoatModelResponse(APIModel):
    id: uuid.UUID
    manufacturer_id: uuid.UUID
    name: str
    hull_type: str | None
    propulsion_type: str | None
    length_ft: float | None
    beam_in: int | None
    is_synthetic: bool
    source_url: str | None
    years: list[int] = []


class BoatModelCreate(StrictInput):
    name: str = Field(min_length=1, max_length=120)
    hull_type: str | None = None
    propulsion_type: str | None = None
    length_ft: float | None = Field(None, gt=0, le=400)
    beam_in: int | None = Field(None, gt=0)
    is_synthetic: bool = False
    source_url: str | None = None


class BoatModelUpdate(StrictInput):
    name: str | None = Field(None, min_length=1, max_length=120)
    hull_type: str | None = None
    propulsion_type: str | None = None
    length_ft: float | None = Field(None, gt=0, le=400)
    beam_in: int | None = Field(None, gt=0)
    is_synthetic: bool | None = None
    source_url: str | None = None


class ManufacturerDetail(ManufacturerResponse):
    models: list[BoatModelResponse] = []


class OEMEquipmentResponse(APIModel):
    id: uuid.UUID
    model_year_id: uuid.UUID
    category: EquipmentCategoryResponse
    equipment_make: str
    equipment_model: str | None
    part_sku: str | None
    is_standard: bool
    data_source: str
    source_url: str | None
    confidence_score: float
    verification_status: str
    is_synthetic: bool
    # True only when the record is confident enough to be presented as fact.
    reliable: bool


class OEMEquipmentCreate(StrictInput):
    category: str = Field(min_length=1, description="equipment category slug")
    equipment_make: str = Field(min_length=1, max_length=100)
    equipment_model: str | None = Field(None, max_length=100)
    part_sku: str | None = None
    is_standard: bool = True
    data_source: DataSource
    source_url: str | None = None
    confidence_score: float | None = Field(None, ge=0, le=1, description="defaults by data_source")
    verification_status: Literal["unverified", "verified", "rejected"] = "unverified"


class OEMEquipmentUpdate(StrictInput):
    category: str | None = None
    equipment_make: str | None = Field(None, min_length=1, max_length=100)
    equipment_model: str | None = None
    part_sku: str | None = None
    is_standard: bool | None = None
    data_source: DataSource | None = None
    source_url: str | None = None
    confidence_score: float | None = Field(None, ge=0, le=1)
    verification_status: Literal["unverified", "verified", "rejected"] | None = None


class ModelYearResponse(APIModel):
    id: uuid.UUID
    boat_model_id: uuid.UUID
    year: int
    brochure_url: str | None
    hin_prefix: str | None
    equipment_count: int = 0


class ModelYearDetail(ModelYearResponse):
    manufacturer: ManufacturerResponse
    boat_model: BoatModelResponse
    equipment: list[OEMEquipmentResponse] = []


class ModelYearCreate(StrictInput):
    year: int = Field(ge=1900, le=2100)
    brochure_url: str | None = None
    hin_prefix: str | None = Field(None, max_length=8)


class ModelYearUpdate(StrictInput):
    brochure_url: str | None = None
    hin_prefix: str | None = Field(None, max_length=8)


class HinDecodeRequest(StrictInput):
    hin: str = Field(min_length=1, max_length=40)


class HinManufacturer(APIModel):
    id: uuid.UUID
    name: str
    is_synthetic: bool


class HinDecodeResponse(APIModel):
    input: str
    normalized: str | None
    valid: bool
    status: Literal["valid", "invalid", "unrecognised"]
    format: str | None
    country_code: str | None
    mic: str | None
    serial: str | None
    production_month: int | None
    production_year: int | None
    model_year: int | None
    manufacturer: HinManufacturer | None
    confidence: float
    warnings: list[str]


class VerificationReview(StrictInput):
    review_note: str | None = Field(None, max_length=2000)


class AdminVerificationItem(APIModel):
    id: uuid.UUID
    vessel_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    submitted_note: str | None
    evidence_url: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    vessel_label: str
    equipment: list[dict] = []
