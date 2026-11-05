"""Vessel (My Vessel Garage) schemas — canonical field names match the database."""

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import APIModel, StrictInput

HULL_TYPES = ("aluminium", "fibreglass", "inflatable", "timber", "steel", "other")
PROPULSION_TYPES = ("outboard", "inboard", "sterndrive", "jet", "sail", "electric", "other")


def _blank_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


class VesselFields(StrictInput):
    hin: str | None = Field(None, max_length=20)
    hull_type: str | None = Field(None, max_length=40)
    length_ft: float | None = Field(None, gt=0, le=400)
    primary_use: str | None = Field(None, max_length=60)
    propulsion_type: str | None = Field(None, max_length=20)
    engine_make: str | None = Field(None, max_length=60)
    engine_model: str | None = Field(None, max_length=60)
    engine_year: int | None = Field(None, ge=1900, le=2100)
    engine_serial: str | None = Field(None, max_length=60)
    engine_hours: int | None = Field(None, ge=0, le=100000)

    _blank = field_validator(
        "hin", "hull_type", "primary_use", "propulsion_type", "engine_make", "engine_model",
        "engine_serial", mode="before",
    )(_blank_to_none)


class VesselCreate(VesselFields):
    nickname: str = Field(min_length=1, max_length=100)
    make: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=1900, le=2100)
    is_primary: bool = False


class VesselUpdate(VesselFields):
    nickname: str | None = Field(None, min_length=1, max_length=100)
    make: str | None = Field(None, min_length=1, max_length=100)
    model: str | None = Field(None, min_length=1, max_length=100)
    year: int | None = Field(None, ge=1900, le=2100)
    is_primary: bool | None = None


class VesselResponse(APIModel):
    id: uuid.UUID
    user_id: uuid.UUID
    nickname: str
    hin: str | None
    hin_status: str | None
    hin_decoded: dict | None
    make: str
    model: str
    year: int
    model_year_id: uuid.UUID | None
    hull_type: str | None
    length_ft: float | None
    primary_use: str | None
    propulsion_type: str | None
    engine_make: str | None
    engine_model: str | None
    engine_year: int | None
    engine_serial: str | None
    engine_hours: int | None
    is_primary: bool
    created_at: datetime
    updated_at: datetime
