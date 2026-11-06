"""Service jobs, contractor organizations, grants and evidence requests (workstream A2).

Contract: docs/04_technical_spec/Service_Jobs_and_Contractor_Assistant_Specification.md
§3, §4, §5.1–5.2, §7.1, §10, §11. Restricted access values (gate codes, keys, contacts,
exact location) never appear in any job, list, inbox or preview model — only in
:class:`AccessRestrictedResponse`, served by its own audited endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.models.service_jobs import JOB_SECTIONS, MEASUREMENT_DIMENSIONS
from app.schemas.common import APIModel, StrictInput

Section = Literal[
    "summary", "evidence", "measurements", "preparation", "access_general", "access_restricted", "scope", "invoices"
]
if set(Section.__args__) != set(JOB_SECTIONS):  # keep the vocabulary in one place
    raise RuntimeError("Section literal out of sync with JOB_SECTIONS")

EntryPoint = Literal["vessel", "first_mate", "service"]
Urgency = Literal["routine", "soon", "urgent", "unknown"]
JobStatus = Literal[
    "draft",
    "evidence_collection",
    "contractor_review",
    "preparation_ready",
    "scheduled",
    "attended",
    "completed",
    "archived",
    "cancelled",
]
# Transitions this API performs; attended/completed are recorded by visits, archive by its endpoint.
TransitionTarget = Literal["evidence_collection", "contractor_review", "preparation_ready", "scheduled", "cancelled"]
EvidenceCategory = Literal[
    "overview",
    "access_route",
    "label",
    "close_up",
    "connections",
    "route",
    "markings",
    "measurement",
    "document",
    "other",
]
EvidenceStatus = Literal["outstanding", "answered", "unavailable", "waived"]
UnavailableReason = Literal["cannot_safely_access", "not_visible", "not_available", "other"]
Priority = Literal["high", "normal", "low"]
Dimension = Literal[
    "hose_internal_diameter",
    "hose_external_diameter",
    "fitting_outside_diameter",
    "thread",
    "clamp_range",
    "route_length",
    "bend_radius",
    "clearance",
    "other",
]
if set(Dimension.__args__) != set(MEASUREMENT_DIMENSIONS):
    raise RuntimeError("Dimension literal out of sync with MEASUREMENT_DIMENSIONS")

Text200 = Field(None, max_length=200)
Text2000 = Field(None, max_length=2000)


def _sections_valid(v: list[str]) -> list[str]:
    out: list[str] = []
    for s in v:
        if s not in out:
            out.append(s)
    if not out:
        raise ValueError("choose at least one section to share")
    return out


# --- Organizations ---------------------------------------------------------------
class OrganizationCreate(StrictInput):
    name: str = Field(min_length=2, max_length=200)
    trading_name: str | None = Field(None, max_length=200)
    nzbn: str | None = Field(None, max_length=20, pattern=r"^[0-9]{13}$")


class OrganizationUpdate(StrictInput):
    status: Literal["active", "suspended"] | None = None
    name: str | None = Field(None, min_length=2, max_length=200)
    trading_name: str | None = Field(None, max_length=200)


class MembershipCreate(StrictInput):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["admin", "member"] = "member"


class OrganizationResponse(APIModel):
    id: uuid.UUID
    name: str
    trading_name: str | None
    nzbn: str | None
    status: str
    created_at: datetime


class DirectoryEntry(APIModel):
    """Public directory row: knowing it grants no access to anything."""

    id: uuid.UUID
    name: str
    trading_name: str | None


class MemberResponse(APIModel):
    user_id: uuid.UUID
    name: str | None
    email: str | None = None  # platform admin / org admin views only
    role: str
    status: str
    verified_at: datetime | None
    removed_at: datetime | None


class MyMembership(APIModel):
    organization_id: uuid.UUID
    name: str
    trading_name: str | None
    role: str
    verified_at: datetime | None


# --- Assignments -------------------------------------------------------------------
class AssignmentInvite(StrictInput):
    organization_id: uuid.UUID
    sections: list[Section] = Field(min_length=1, max_length=len(JOB_SECTIONS))
    live_updates: bool = False

    _sections = field_validator("sections")(_sections_valid)


class AssignmentUpdate(StrictInput):
    expected_version: int = Field(ge=1)
    sections: list[Section] | None = Field(None, min_length=1, max_length=len(JOB_SECTIONS))
    live_updates: bool | None = None

    @field_validator("sections")
    @classmethod
    def _sections(cls, v):
        return None if v is None else _sections_valid(v)


class RestrictedAccessUpdate(StrictInput):
    restricted_access: bool
    expected_version: int | None = Field(None, ge=1)


class AssignmentRevoke(StrictInput):
    reason: str | None = Field(None, max_length=500)


class AssignmentAccept(StrictInput):
    member_user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class AssignmentMemberAdd(StrictInput):
    user_id: uuid.UUID


class AssignmentMemberResponse(APIModel):
    user_id: uuid.UUID
    name: str | None
    restricted_access: bool
    added_at: datetime


class OrganizationRef(APIModel):
    id: uuid.UUID
    name: str
    trading_name: str | None


class AssignmentResponse(APIModel):
    """The owner's view of a grant (and the assigned contractor's own grant)."""

    id: uuid.UUID
    job_id: uuid.UUID
    organization: OrganizationRef
    status: str
    sections: list[str]
    live_updates: bool
    invited_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    version: int
    members: list[AssignmentMemberResponse]


class InvitationSummary(APIModel):
    """What an organization administrator sees of an invitation: no evidence, no access."""

    assignment_id: uuid.UUID
    job_id: uuid.UUID
    organization_id: uuid.UUID
    status: str
    job_title: str
    vessel_make: str | None
    vessel_model: str | None
    sections: list[str]
    live_updates: bool
    inviter_first_name: str | None
    invited_at: datetime
    accepted_at: datetime | None
    version: int
    members: list[AssignmentMemberResponse]


class SectionPreview(APIModel):
    section: str
    label: str
    exposes: list[str]
    counts: dict[str, int]
    note: str | None = None


class SharingPreview(APIModel):
    organization: OrganizationRef
    sections: list[SectionPreview]
    withheld: list[str]
    live_updates: bool
    live_updates_note: str


class InboxJob(APIModel):
    job_id: uuid.UUID
    title: str
    status: str
    assignment_id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    sections: list[str]
    restricted_access: bool
    accepted_at: datetime | None
    updated_at: datetime


class ContractorInbox(APIModel):
    assigned: list[InboxJob]
    invitations: list[InvitationSummary]


# --- Jobs ------------------------------------------------------------------------
class JobCreate(StrictInput):
    vessel_id: uuid.UUID
    entry_point: EntryPoint = "vessel"
    title: str = Field(min_length=1, max_length=200)
    issue_description: str = Field("", max_length=4000)
    affected_system: str | None = Text200
    affected_equipment: str | None = Text200
    occurs_when: str | None = Text2000
    already_tried: str | None = Text2000
    urgency: Urgency = "unknown"


class JobUpdate(StrictInput):
    expected_version: int = Field(ge=1)
    title: str | None = Field(None, min_length=1, max_length=200)
    issue_description: str | None = Field(None, max_length=4000)
    affected_system: str | None = Text200
    affected_equipment: str | None = Text200
    occurs_when: str | None = Text2000
    already_tried: str | None = Text2000
    urgency: Urgency | None = None


class VesselContextVessel(StrictInput):
    make: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    year: int | None = Field(None, ge=1900, le=2100)
    hull_type: str | None = Field(None, max_length=40)
    propulsion_type: str | None = Field(None, max_length=20)
    length_ft: float | None = Field(None, gt=0, le=400)


class VesselContextEngine(StrictInput):
    make: str | None = Field(None, max_length=60)
    model: str | None = Field(None, max_length=60)
    year: int | None = Field(None, ge=1900, le=2100)


class VesselContextEquipment(StrictInput):
    category: str = Field(min_length=1, max_length=60)
    make: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    year: int | None = Field(None, ge=1900, le=2100)


class VesselContextCorrection(StrictInput):
    """Explicit owner correction of the snapshot taken at job creation (bumps the evidence revision)."""

    expected_version: int = Field(ge=1)
    vessel: VesselContextVessel | None = None
    engine: VesselContextEngine | None = None
    equipment: list[VesselContextEquipment] | None = Field(None, max_length=50)
    note: str | None = Field(None, max_length=500)


class JobTransition(StrictInput):
    expected_version: int = Field(ge=1)
    to: TransitionTarget
    note: str | None = Field(None, max_length=500)


class JobVersioned(StrictInput):
    expected_version: int = Field(ge=1)


class Viewer(APIModel):
    role: str
    sections: list[str]
    organization_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    restricted_access: bool


class GapResponse(APIModel):
    request_id: uuid.UUID
    category: str
    component: str | None
    prompt: str
    reason: str | None
    note: str | None
    technician_inspection_required: bool


class EvidenceRequestResponse(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    requester_role: str
    organization_id: uuid.UUID | None
    category: str
    component: str | None
    prompt: str
    reason: str
    measurement_dimension: str | None
    priority: str
    status: str
    unavailable_reason: str | None
    technician_inspection_required: bool
    answer_note: str | None
    answered_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    options: list[str]


class EvidenceSummary(APIModel):
    outstanding: list[EvidenceRequestResponse]
    answered: list[EvidenceRequestResponse]
    unavailable: list[EvidenceRequestResponse]
    waived: list[EvidenceRequestResponse]
    available_asset_count: int


class JobResponse(APIModel):
    """Filtered by the viewer: fields of ungranted sections are null/absent."""

    id: uuid.UUID
    vessel_id: uuid.UUID | None
    entry_point: str
    title: str
    status: str
    version: int
    evidence_revision: int
    disputed: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    viewer: Viewer
    # "summary" section
    issue_description: str | None = None
    affected_system: str | None = None
    affected_equipment: str | None = None
    occurs_when: str | None = None
    already_tried: str | None = None
    urgency: str | None = None
    vessel_context: dict | None = None
    # "evidence" section
    evidence: EvidenceSummary | None = None
    gaps: list[GapResponse] | None = None
    technician_inspection_required: bool | None = None
    # owner: the live assignment; contractor: their own
    assignment: AssignmentResponse | None = None


class JobListItem(APIModel):
    id: uuid.UUID
    vessel_id: uuid.UUID | None
    title: str
    status: str
    urgency: str
    version: int
    outstanding_requests: int
    gap_count: int
    assignment_status: str | None
    created_at: datetime
    updated_at: datetime


# --- Access details -------------------------------------------------------------------
class AccessGeneral(StrictInput):
    """Logistics shared with the ``access_general`` section."""

    marina: str | None = Text200
    mooring_area: str | None = Text200
    rendezvous: str | None = Text200
    parking_loading: str | None = Field(None, max_length=500)
    access_hours: str | None = Text200
    owner_attendance: str | None = Text200
    locker_panel_access: str | None = Field(None, max_length=500)
    obstructions: str | None = Field(None, max_length=500)
    power_availability: str | None = Text200
    water_availability: str | None = Text200
    known_hazards: str | None = Field(None, max_length=1000)
    notes: str | None = Field(None, max_length=1000)


class AccessRestricted(StrictInput):
    """Credentials/exact location: revealed only to owner-authorized assigned members."""

    gate_code: str | None = Field(None, max_length=100)
    key_handover: str | None = Field(None, max_length=500)
    contact_name: str | None = Field(None, max_length=120)
    contact_phone: str | None = Field(None, max_length=40)
    berth: str | None = Field(None, max_length=100)
    exact_location: str | None = Field(None, max_length=300)
    security_notes: str | None = Field(None, max_length=1000)


class AccessGeneralUpdate(StrictInput):
    expected_version: int = Field(ge=1)
    general: AccessGeneral


class AccessRestrictedUpdate(StrictInput):
    expected_version: int = Field(ge=1)
    restricted: AccessRestricted


class AccessGeneralResponse(APIModel):
    job_id: uuid.UUID
    general: dict
    version: int
    updated_at: datetime


class AccessRestrictedResponse(APIModel):
    job_id: uuid.UUID
    restricted: dict
    version: int
    updated_at: datetime


# --- Evidence requests ------------------------------------------------------------------
class EvidenceRequestCreate(StrictInput):
    category: EvidenceCategory
    prompt: str = Field(min_length=3, max_length=500)
    reason: str = Field(min_length=3, max_length=1000)
    component: str | None = Field(None, max_length=120)
    measurement_dimension: Dimension | None = None
    priority: Priority | None = None


class EvidenceAnswer(StrictInput):
    note: str = Field(min_length=1, max_length=4000)
    expected_version: int | None = Field(None, ge=1)


class EvidenceUnavailable(StrictInput):
    reason: UnavailableReason
    note: str | None = Field(None, max_length=2000)
    expected_version: int | None = Field(None, ge=1)


class EvidenceWaive(StrictInput):
    note: str | None = Field(None, max_length=2000)
    expected_version: int | None = Field(None, ge=1)


class GuidanceProposal(APIModel):
    key: str
    category: str
    component: str | None
    prompt: str
    reason: str
    priority: str
    measurement_dimension: str | None
    safety_note: str
    options: list[str]


class NextEvidence(APIModel):
    """The next useful thing to do: an existing outstanding request, else a proposal, else done."""

    request: EvidenceRequestResponse | None
    proposal: GuidanceProposal | None
    complete: bool
    message: str
    gaps: list[GapResponse]
