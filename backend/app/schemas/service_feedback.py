"""Visits, reciprocal feedback, responses/reports and moderation cases (spec §9, §11)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StrictInt

from app.schemas.common import APIModel, StrictInput

Rating = Annotated[StrictInt, Field(ge=1, le=5)] | Literal["not_applicable"]
Direction = Literal["owner_to_contractor", "contractor_to_owner"]


# Requests ------------------------------------------------------------------------------
class VisitCreate(StrictInput):
    kind: Literal["scheduled", "attended", "completed", "cancelled"]
    occurred_at: AwareDatetime
    note: str | None = Field(default=None, max_length=2000)
    expected_version: int | None = Field(default=None, ge=1)


class VisitContest(StrictInput):
    reason: str = Field(min_length=3, max_length=2000)


class FeedbackDraft(StrictInput):
    """Full replacement of the draft. Omitted questions stay unanswered (never zero)."""

    ratings: dict[str, Rating] = Field(default_factory=dict, max_length=10)
    narrative: str | None = Field(default=None, max_length=4000)
    expected_version: int | None = Field(default=None, ge=0)


class FeedbackSubmit(StrictInput):
    expected_version: int | None = Field(default=None, ge=1)


class FeedbackResponseCreate(StrictInput):
    kind: Literal["response", "correction_request", "addendum"]
    text: str = Field(min_length=1, max_length=4000)


class FeedbackReportCreate(StrictInput):
    category: Literal["factual_dispute", "opinion", "harassment", "personal_or_security_information", "other"]
    reason: str = Field(min_length=3, max_length=2000)
    restrict_content: bool = False


class ModerationActionCreate(StrictInput):
    action: Literal["assign", "restrict", "unrestrict", "resolve"]
    reason: str = Field(min_length=3, max_length=2000)
    disposition: (
        Literal[
            "no_action",
            "addendum_requested",
            "content_restricted",
            "content_removed_for_personal_information",
            "eligibility_corrected",
        ]
        | None
    ) = None
    assignee_id: uuid.UUID | None = None


# Responses -----------------------------------------------------------------------------
class VisitEventOut(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    assignment_id: uuid.UUID | None
    kind: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    actor_role: str
    occurred_at: datetime
    recorded_at: datetime
    note: str | None
    contests_event_id: uuid.UUID | None
    contested: bool


class VisitResult(APIModel):
    event: VisitEventOut
    job_status: str
    job_version: int
    job_disputed: bool
    feedback_window_opened: bool
    created: bool


class ContestResult(APIModel):
    event: VisitEventOut
    case_id: uuid.UUID | None
    job_status: str
    job_version: int
    job_disputed: bool
    created: bool


class PersonRef(APIModel):
    id: uuid.UUID
    name: str | None
    role: Literal["owner", "contractor"]


class OrgRef(APIModel):
    id: uuid.UUID
    name: str | None


class FeedbackResponseOut(APIModel):
    id: uuid.UUID
    kind: str
    author: PersonRef
    text: str | None
    content_state: str
    created_at: datetime


class FeedbackOut(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    direction: Direction
    status: str
    version: int
    author: PersonRef
    organization: OrgRef
    basis: str
    visit_date: datetime | None
    ratings: dict[str, int | Literal["not_applicable"]]
    narrative: str | None
    content_state: Literal["visible", "under_review", "restricted", "removed"]
    submitted_at: datetime | None
    revealed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    responses: list[FeedbackResponseOut]


class FeedbackWindowOut(APIModel):
    basis: str
    opens_at: datetime
    closes_at: datetime
    is_open: bool
    revealed: bool
    revealed_at: datetime | None


class DimensionOut(APIModel):
    key: str
    label: str


class FeedbackOverview(APIModel):
    job_id: uuid.UUID
    my_side: Literal["owner", "contractor"]
    my_direction: Direction
    eligible: bool
    ineligible_reason: str | None
    window: FeedbackWindowOut | None
    reveal_rule: str
    dimensions: list[DimensionOut]
    can_edit: bool
    mine: FeedbackOut | None
    theirs: FeedbackOut | None


class ReportOut(APIModel):
    id: uuid.UUID
    feedback_id: uuid.UUID | None
    category: str
    status: str
    restrict_content: bool
    created_at: datetime


class CaseSummary(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    feedback_id: uuid.UUID | None
    visit_event_id: uuid.UUID | None
    category: str
    status: str
    restrict_content: bool
    assigned_moderator_id: uuid.UUID | None
    content_version: int | None
    disposition: str | None
    retention_hold: bool
    created_at: datetime
    resolved_at: datetime | None


class CaseJobContext(APIModel):
    id: uuid.UUID
    title: str
    status: str
    disputed: bool
    organization_name: str | None


class CaseReporter(APIModel):
    id: uuid.UUID
    name: str | None


class ReportedContent(APIModel):
    version: int
    ratings: dict[str, int | Literal["not_applicable"]]
    narrative: str | None


class CaseActionOut(APIModel):
    id: uuid.UUID
    action: str
    actor_id: uuid.UUID
    reason: str
    content_version: int | None
    created_at: datetime


class CaseDetail(CaseSummary):
    reason: str
    disposition_note: str | None
    reporter: CaseReporter
    job: CaseJobContext
    feedback: FeedbackOut | None
    reported_content: ReportedContent | None
    visit_event: VisitEventOut | None
    contest_event: VisitEventOut | None
    actions: list[CaseActionOut]
