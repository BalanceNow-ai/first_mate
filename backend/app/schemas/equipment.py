"""Vessel equipment, profile verification, service records and reminders."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.boat_db import EquipmentCategoryResponse
from app.schemas.common import APIModel, StrictInput

# verified          : staff-verified (or verified source data)
# owner_declared    : the owner's own statement about their boat
# high_confidence   : OEM database record at or above FITMENT_MIN_CONFIDENCE
# unconfirmed       : low-confidence / unverified OEM data — never presented as fact
Reliability = Literal["verified", "owner_declared", "high_confidence", "unconfirmed"]


class EquipmentItem(APIModel):
    id: uuid.UUID  # vessel_equipment id, or oem_equipment id when source == factory_oem
    source: Literal["installed", "factory_oem"]
    vessel_id: uuid.UUID
    category: EquipmentCategoryResponse
    make: str
    model: str | None
    serial_number: str | None = None
    year: int | None = None
    origin: Literal["oem", "user_added"]
    provenance: str  # owner_declared | oem_database | staff_verified
    data_source: str | None = None  # OEM records only
    confidence_score: float
    verification_status: str
    reliability: Reliability
    is_standard: bool | None = None  # OEM records only
    is_synthetic: bool = False
    oem_equipment_id: uuid.UUID | None = None
    installed_on: date | None = None
    removed_at: datetime | None = None
    notes: str | None = None
    display_note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EquipmentListResponse(APIModel):
    vessel_id: uuid.UUID
    model_year_id: uuid.UUID | None
    items: list[EquipmentItem]


class EquipmentCreate(StrictInput):
    category: str = Field(min_length=1, description="equipment category slug")
    make: str = Field(min_length=1, max_length=100)
    model: str | None = Field(None, max_length=100)
    serial_number: str | None = Field(None, max_length=100)
    year: int | None = Field(None, ge=1900, le=2100)
    installed_on: date | None = None
    notes: str | None = Field(None, max_length=2000)


class EquipmentUpdate(StrictInput):
    category: str | None = None
    make: str | None = Field(None, min_length=1, max_length=100)
    model: str | None = Field(None, max_length=100)
    serial_number: str | None = Field(None, max_length=100)
    year: int | None = Field(None, ge=1900, le=2100)
    installed_on: date | None = None
    notes: str | None = Field(None, max_length=2000)


class ApplyOEMRequest(StrictInput):
    oem_equipment_ids: list[uuid.UUID] | None = Field(
        None, description="Subset of the linked model year's OEM records; default all"
    )


class ApplyOEMResponse(APIModel):
    created: list[EquipmentItem]
    skipped_already_applied: list[uuid.UUID]


class VerificationRequestCreate(StrictInput):
    note: str | None = Field(None, max_length=2000)
    evidence_url: str | None = Field(None, max_length=500)
    equipment_ids: list[uuid.UUID] | None = Field(
        None, description="Installed rows to review; default all unverified rows"
    )


class VerificationRequestResponse(APIModel):
    id: uuid.UUID
    vessel_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    submitted_note: str | None
    evidence_url: str | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    equipment_ids: list[uuid.UUID] = []


class ServiceRecordCreate(StrictInput):
    service_type: str = Field(min_length=1, max_length=120)
    performed_on: date
    engine_hours: int | None = Field(None, ge=0, le=100000)
    provider_name: str | None = Field(None, max_length=200)
    cost_cents: int | None = Field(None, ge=0, le=100_000_000)
    notes: str | None = Field(None, max_length=4000)
    equipment_id: uuid.UUID | None = None


class ServiceRecordUpdate(StrictInput):
    service_type: str | None = Field(None, min_length=1, max_length=120)
    performed_on: date | None = None
    engine_hours: int | None = Field(None, ge=0, le=100000)
    provider_name: str | None = Field(None, max_length=200)
    cost_cents: int | None = Field(None, ge=0, le=100_000_000)
    notes: str | None = Field(None, max_length=4000)
    equipment_id: uuid.UUID | None = None


class ServiceRecordResponse(APIModel):
    id: uuid.UUID
    vessel_id: uuid.UUID
    equipment_id: uuid.UUID | None
    service_type: str
    performed_on: date
    engine_hours: int | None
    provider_name: str | None
    cost_cents: int | None
    currency: str = "NZD"
    notes: str | None
    created_at: datetime


class ReminderCreate(StrictInput):
    title: str = Field(min_length=1, max_length=200)
    due_on: date | None = None
    due_engine_hours: int | None = Field(None, ge=0, le=100000)
    interval_months: int | None = Field(None, ge=1, le=120)
    interval_hours: int | None = Field(None, ge=1, le=10000)
    equipment_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _has_due(self):
        if self.due_on is None and self.due_engine_hours is None:
            raise ValueError("Set due_on and/or due_engine_hours")
        return self


class ReminderUpdate(StrictInput):
    title: str | None = Field(None, min_length=1, max_length=200)
    due_on: date | None = None
    due_engine_hours: int | None = Field(None, ge=0, le=100000)
    interval_months: int | None = Field(None, ge=1, le=120)
    interval_hours: int | None = Field(None, ge=1, le=10000)
    equipment_id: uuid.UUID | None = None
    status: Literal["active", "dismissed"] | None = None


class ReminderComplete(StrictInput):
    completed_on: date | None = None  # default today
    engine_hours: int | None = Field(None, ge=0, le=100000)  # default vessel.engine_hours
    record_service: bool = True
    notes: str | None = Field(None, max_length=4000)


class ReminderResponse(APIModel):
    id: uuid.UUID
    vessel_id: uuid.UUID
    equipment_id: uuid.UUID | None
    title: str
    due_on: date | None
    due_engine_hours: int | None
    interval_months: int | None
    interval_hours: int | None
    status: str
    source: str
    is_due: bool = False
    created_at: datetime
    updated_at: datetime


class ReminderCompleteResponse(APIModel):
    completed: ReminderResponse
    next: ReminderResponse | None
    service_record: ServiceRecordResponse | None
