"""Vessel Pydantic schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class VesselBase(BaseModel):
    nickname: str = Field(min_length=1, max_length=100)
    hin: str | None = Field(None, max_length=14)
    make: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=1900, le=2030)
    hull_type: str | None = None
    length_ft: int | None = None
    primary_use: str | None = None
    engine_make: str | None = None
    engine_model: str | None = None
    engine_serial: str | None = None
    engine_hours: int | None = Field(None, ge=0)
    is_primary: bool = False


class VesselCreate(VesselBase):
    pass


class VesselUpdate(BaseModel):
    nickname: str | None = Field(None, min_length=1, max_length=100)
    hin: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = Field(None, ge=1900, le=2030)
    hull_type: str | None = None
    length_ft: int | None = None
    primary_use: str | None = None
    engine_make: str | None = None
    engine_model: str | None = None
    engine_serial: str | None = None
    engine_hours: int | None = Field(None, ge=0)
    is_primary: bool | None = None


class VesselResponse(VesselBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
